from __future__ import annotations

import base64
import io
import imghdr
import logging
import mimetypes
import re
import shlex
import subprocess
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pypdf import PdfReader

from app.asset_search import AssetCatalog
from app.config import load_settings
from app.models import (
    AssetCatalogResponse,
    AssetIndexRequest,
    AssetIndexResponse,
    BaselineAdoptRequest,
    BaselineSkipRequest,
    BaselineSkipResponse,
    ChatRequest,
    ChatResponse,
    EditRecommendationsResponse,
    BriefUploadResponse,
    Preview3DGenerateRequest,
    Preview3DGenerateResponse,
    VersionApproveRequest,
    VersionApproveResponse,
    ImageEditRequest,
    ImageGenerateRequest,
    ImageResponse,
    ImageVersion,
    SessionResponse,
    SessionClearRequest,
    SessionClearResponse,
)
from app.rate_limit import SimpleRateLimiter
from app.recommendations import build_edit_recommendations
from app.storage import SessionStore
from app.straive_client import StraiveClient
from app.workflow import (
    WORKFLOW_SYSTEM_PROMPT,
    handle_chat_turn,
    missing_fields,
    required_questions_for_missing,
    spec_summary,
    update_spec_from_message,
)

settings = load_settings()
Path(settings.triposr_output_dir).mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger("pack-design-app")

app = FastAPI(title="AI-Powered Intelligent Pack Design", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = SessionStore(settings.db_path)
asset_catalog = AssetCatalog(settings.db_path, settings.assets_dir)
straive = StraiveClient(settings)
limiter = SimpleRateLimiter(max_requests=120, window_seconds=60)

STRICT_MESSAGES = {
    "Searching for a similar baseline design…",
    "No close baseline found. Creating a new concept.",
    "Please approve a version from Version History, then generate the 3D preview.",
}
BASELINE_SEARCH_MSG = "Searching for a similar baseline design…"
BASELINE_NEW_MSG = "No close baseline found. Creating a new concept."
SESSION_IMAGE_DIR = Path("session_images")


def _request_api_key(request: Request) -> str | None:
    value = request.headers.get("X-Straive-Api-Key", "").strip()
    return value or None


def _normalize_image_ref_for_edit(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return raw
    p = Path(raw)
    if p.exists() and p.is_file():
        return str(p)
    if raw.startswith("http://") or raw.startswith("https://") or raw.startswith("data:image"):
        return raw
    # Straive may return bare base64 for generated images; normalize to data URL for edit calls.
    return f"data:image/png;base64,{raw}"


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    chunks: list[str] = []
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        if txt.strip():
            chunks.append(txt.strip())
    return "\n\n".join(chunks).strip()


def _safe_session_key(session_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", session_id)[:100]


def _detect_mime_from_bytes(blob: bytes, hinted: str | None = None) -> str:
    kind = imghdr.what(None, h=blob)
    mapping = {
        "png": "image/png",
        "jpeg": "image/jpeg",
        "jpg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
        "bmp": "image/bmp",
    }
    if kind and kind.lower() in mapping:
        return mapping[kind.lower()]
    if hinted and hinted.startswith("image/"):
        return hinted
    return "image/png"


async def _resolve_image_bytes(value: str, req_api_key: str | None = None) -> tuple[bytes, str]:
    raw = (value or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty image content.")

    p = Path(raw)
    if p.exists() and p.is_file():
        blob = p.read_bytes()
        hinted = mimetypes.guess_type(str(p))[0]
        return blob, _detect_mime_from_bytes(blob, hinted=hinted)

    if raw.startswith("data:image"):
        header, b64_data = raw.split(",", 1)
        m = re.search(r"data:(image/[^;]+);base64", header)
        hinted = m.group(1) if m else None
        blob = base64.b64decode(b64_data)
        return blob, _detect_mime_from_bytes(blob, hinted=hinted)

    if raw.startswith("http://") or raw.startswith("https://"):
        headers = {}
        if req_api_key:
            headers["Authorization"] = f"Bearer {req_api_key}"
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.get(raw, headers=headers)
            resp.raise_for_status()
            blob = resp.content
            hinted = resp.headers.get("content-type", "").split(";")[0].strip() or None
            return blob, _detect_mime_from_bytes(blob, hinted=hinted)

    # Assume bare base64.
    blob = base64.b64decode(raw)
    return blob, _detect_mime_from_bytes(blob, hinted=None)


async def _materialize_session_image(
    session_id: str, version: int, image_value: str, req_api_key: str | None = None
) -> tuple[str, str]:
    blob, mime_type = await _resolve_image_bytes(image_value, req_api_key=req_api_key)
    ext = mimetypes.guess_extension(mime_type) or ".png"
    sess_dir = SESSION_IMAGE_DIR / _safe_session_key(session_id)
    sess_dir.mkdir(parents=True, exist_ok=True)
    local_path = sess_dir / f"v{version}{ext}"
    local_path.write_bytes(blob)
    data_url = f"data:{mime_type};base64,{base64.b64encode(blob).decode('utf-8')}"
    return data_url, str(local_path.resolve())


def _run_triposr(input_image_path: str, session_id: str) -> str:
    if not settings.triposr_command.strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "TRIPOSR_COMMAND is not configured. Set env var, e.g. "
                "'python run.py --input {input} --output-dir {output_dir}'"
            ),
        )

    output_root = Path(settings.triposr_output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    run_dir = output_root / f"{_safe_session_key(session_id)}-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)

    command = settings.triposr_command.format(input=input_image_path, output_dir=str(run_dir))
    args = shlex.split(command)
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail=f"TripoSR timed out: {exc}") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"TripoSR command not found: {exc}") from exc

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise HTTPException(status_code=502, detail=f"TripoSR failed: {err[:500]}")

    candidates = []
    for ext in (".glb", ".obj", ".ply", ".stl"):
        candidates.extend(run_dir.rglob(f"*{ext}"))
    if not candidates:
        raise HTTPException(status_code=502, detail="TripoSR completed but no 3D file was found.")

    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    return str(latest.resolve())


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    limiter.check(request, "chat")
    state = store.get_or_create(payload.session_id)
    req_api_key = _request_api_key(request)

    deterministic_message, flags = handle_chat_turn(state, payload.user_message)

    # Only use LLM for style polish when workflow constraints are already satisfied by deterministic logic.
    assistant_message = deterministic_message
    if deterministic_message in {BASELINE_SEARCH_MSG, BASELINE_NEW_MSG}:
        if settings.auto_index_assets:
            try:
                indexed_count, total_assets = await asset_catalog.index_assets(
                    straive=straive, force_reindex=False, api_key_override=req_api_key
                )
                if indexed_count:
                    logger.info(
                        "Auto-indexed %s new assets before baseline search (total assets: %s).",
                        indexed_count,
                        total_assets,
                    )
            except Exception as exc:
                logger.warning("Auto asset indexing failed; continuing with existing metadata. error=%s", exc)
        matches = asset_catalog.find_matches(state.spec, min_score=2, limit=5)
        state.baseline_matches = matches
        if not any(
            state.baseline_asset and state.baseline_asset.get("asset_rel_path") == m.get("asset_rel_path")
            for m in matches
        ):
            state.baseline_asset = None
        assistant_message = BASELINE_SEARCH_MSG if matches else BASELINE_NEW_MSG
        state.baseline_decision = assistant_message
        if state.history and state.history[-1].get("role") == "assistant":
            state.history[-1]["content"] = assistant_message

    if deterministic_message not in STRICT_MESSAGES:
        try:
            polished = await straive.chat(
                system_prompt=WORKFLOW_SYSTEM_PROMPT,
                history=state.history[-8:],
                user_message=(
                    "Rewrite this response with concise senior packaging engineer tone while preserving exact meaning and workflow constraints: "
                    + deterministic_message
                ),
                api_key_override=req_api_key,
            )
            if polished:
                assistant_message = polished.strip()
                if state.history and state.history[-1].get("role") == "assistant":
                    state.history[-1]["content"] = assistant_message
        except Exception as exc:
            logger.warning("Chat polish failed, using deterministic response. error=%s", exc)

    store.save(state)
    return ChatResponse(
        assistant_message=assistant_message,
        step=state.step,
        spec_summary=spec_summary(state.spec),
        required_questions=flags["required_questions"],
        can_generate_image=flags["can_generate_image"],
        can_iterate_image=flags["can_iterate_image"],
        can_lock=flags["can_lock"],
        can_generate_cad=False,
    )


@app.post("/api/brief/upload", response_model=BriefUploadResponse)
async def upload_marketing_brief(
    request: Request,
    session_id: str = Form(...),
    file: UploadFile = File(...),
) -> BriefUploadResponse:
    limiter.check(request, "brief-upload")
    req_api_key = _request_api_key(request)

    filename = (file.filename or "").lower()
    if not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported for marketing brief upload.")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded PDF is empty.")
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF is too large. Maximum supported size is 12 MB.")

    text = _extract_pdf_text(raw)
    if not text:
        raise HTTPException(status_code=400, detail="Could not extract readable text from PDF.")

    state = store.get_or_create(session_id)
    update_spec_from_message(state.spec, text)

    try:
        extracted = await straive.extract_design_spec_from_brief(text, api_key_override=req_api_key)
    except Exception as exc:
        logger.warning("Brief AI extraction failed; using deterministic parse only. error=%s", exc)
        extracted = {}

    for field in ["product_type", "size_or_volume", "intended_material", "closure_type", "design_style"]:
        value = extracted.get(field)
        if isinstance(value, str) and value.strip():
            setattr(state.spec, field, value.strip().lower())

    dims = extracted.get("dimensions", {})
    if isinstance(dims, dict):
        for k, v in dims.items():
            try:
                state.spec.dimensions[str(k)] = float(v)
            except (TypeError, ValueError):
                continue

    state.missing_fields = missing_fields(state.spec)
    state.required_questions = required_questions_for_missing(state.missing_fields)
    state.baseline_decision = None
    state.baseline_decision_done = False
    state.baseline_matches = []
    state.baseline_asset = None
    state.history.append({"role": "system", "content": f"Marketing brief uploaded: {file.filename}"})

    if state.missing_fields:
        state.step = 1
        message = "Marketing brief processed. Some mandatory fields are still missing."
    else:
        state.step = 3
        message = "Marketing brief processed. Design spec extracted and ready for baseline search."

    store.save(state)
    return BriefUploadResponse(
        message=message,
        step=state.step,
        spec_summary=spec_summary(state.spec),
        required_questions=state.required_questions,
    )


@app.post("/api/assets/index", response_model=AssetIndexResponse)
async def index_assets(payload: AssetIndexRequest, request: Request) -> AssetIndexResponse:
    limiter.check(request, "assets-index")
    req_api_key = _request_api_key(request)
    indexed_count, total_assets = await asset_catalog.index_assets(
        straive=straive, force_reindex=payload.force_reindex, api_key_override=req_api_key
    )
    return AssetIndexResponse(indexed_count=indexed_count, total_assets=total_assets)


@app.get("/api/assets/catalog", response_model=AssetCatalogResponse)
async def asset_catalog_list(request: Request) -> AssetCatalogResponse:
    limiter.check(request, "assets-catalog")
    items = asset_catalog.list_catalog(limit=300)
    return AssetCatalogResponse(total=len(items), items=items)


@app.get("/api/recommendations/{session_id}", response_model=EditRecommendationsResponse)
async def get_recommendations(session_id: str, request: Request) -> EditRecommendationsResponse:
    limiter.check(request, "recommendations")
    state = store.get_or_create(session_id)
    recs = build_edit_recommendations(state.spec)
    return EditRecommendationsResponse(count=len(recs), recommendations=recs)


@app.post("/api/image/generate", response_model=ImageResponse)
async def image_generate(payload: ImageGenerateRequest, request: Request) -> ImageResponse:
    limiter.check(request, "image-generate")
    state = store.get_or_create(payload.session_id)
    req_api_key = _request_api_key(request)

    if state.step < 3:
        raise HTTPException(status_code=400, detail="Workflow has not reached STEP 3.")

    generated = await straive.image_generate(payload.prompt, api_key_override=req_api_key)
    version = len(state.images) + 1
    image_data_url, local_path = await _materialize_session_image(
        payload.session_id, version, generated["image_url_or_base64"], req_api_key=req_api_key
    )
    image = ImageVersion(
        image_id=generated["image_id"] or str(uuid.uuid4()),
        image_url_or_base64=image_data_url,
        version=version,
        prompt=payload.prompt,
        local_image_path=local_path,
    )
    state.images.append(image)

    # New concept generation should always move workflow into active 2D iteration mode.
    state.step = 4
    state.lock_question_asked = False
    state.lock_confirmed = False
    state.design_summary = None
    state.approved_image_id = None
    state.approved_image_version = None
    state.approved_image_local_path = None
    state.preview_3d_file = None

    store.save(state)
    return ImageResponse(
        image_id=image.image_id,
        image_url_or_base64=image.image_url_or_base64,
        version=image.version,
    )


@app.post("/api/image/edit", response_model=ImageResponse)
async def image_edit(payload: ImageEditRequest, request: Request) -> ImageResponse:
    limiter.check(request, "image-edit")
    state = store.get_or_create(payload.session_id)
    req_api_key = _request_api_key(request)

    if not state.images:
        raise HTTPException(status_code=400, detail="No reference image found. Generate or adopt a concept first.")
    if state.lock_confirmed:
        raise HTTPException(status_code=400, detail="Design is locked. Iteration is not allowed.")
    if state.step < 4:
        state.step = 4

    # Always edit the latest session visual so iteration is continuous from the current reference.
    latest = state.images[-1] if state.images else None
    latest_ref = (
        latest.local_image_path
        if latest and latest.local_image_path
        else (latest.image_url_or_base64 if latest else payload.image_id)
    )
    latest_ref = _normalize_image_ref_for_edit(latest_ref)
    try:
        edited = await straive.image_edit(latest_ref, payload.instruction_prompt, api_key_override=req_api_key)
    except Exception as exc:
        logger.error("Image edit failed. session=%s error=%s", payload.session_id, exc)
        raise HTTPException(status_code=502, detail=f"Image edit failed: {exc}") from exc
    version = len(state.images) + 1
    image_data_url, local_path = await _materialize_session_image(
        payload.session_id, version, edited["image_url_or_base64"], req_api_key=req_api_key
    )
    image = ImageVersion(
        image_id=edited["image_id"] or str(uuid.uuid4()),
        image_url_or_base64=image_data_url,
        version=version,
        prompt=payload.instruction_prompt,
        local_image_path=local_path,
    )
    state.images.append(image)
    state.approved_image_id = None
    state.approved_image_version = None
    state.approved_image_local_path = None
    state.preview_3d_file = None

    store.save(state)
    return ImageResponse(
        image_id=image.image_id,
        image_url_or_base64=image.image_url_or_base64,
        version=image.version,
    )


@app.post("/api/image/adopt-baseline", response_model=ImageResponse)
async def adopt_baseline(payload: BaselineAdoptRequest, request: Request) -> ImageResponse:
    limiter.check(request, "image-adopt-baseline")
    state = store.get_or_create(payload.session_id)
    match = next((m for m in state.baseline_matches if m.get("asset_rel_path") == payload.asset_rel_path), None)
    if not match:
        raise HTTPException(status_code=400, detail="Selected baseline match is not available for this session.")
    state.baseline_asset = match

    asset_path = Path(match["asset_path"])
    if not asset_path.exists() or not asset_path.is_file():
        raise HTTPException(status_code=404, detail="Baseline asset file not found.")

    mime_type = mimetypes.guess_type(str(asset_path))[0] or "image/png"
    b64 = base64.b64encode(asset_path.read_bytes()).decode("utf-8")
    data_url = f"data:{mime_type};base64,{b64}"
    version = len(state.images) + 1
    image = ImageVersion(
        image_id=f"baseline-{uuid.uuid4()}",
        image_url_or_base64=data_url,
        version=version,
        prompt=f"Adopted baseline asset: {match.get('filename', asset_path.name)}",
        local_image_path=str(asset_path.resolve()),
    )
    state.images.append(image)
    state.approved_image_id = None
    state.approved_image_version = None
    state.approved_image_local_path = None
    state.preview_3d_file = None
    if state.step < 4:
        state.step = 4
    store.save(state)
    return ImageResponse(
        image_id=image.image_id,
        image_url_or_base64=image.image_url_or_base64,
        version=image.version,
    )


@app.post("/api/version/approve", response_model=VersionApproveResponse)
async def approve_version(payload: VersionApproveRequest, request: Request) -> VersionApproveResponse:
    limiter.check(request, "version-approve")
    state = store.get_or_create(payload.session_id)
    target = next((img for img in state.images if img.version == payload.version), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"Version v{payload.version} not found.")
    if not target.local_image_path:
        # Repair local path if old state row lacks it.
        data_url, local_path = await _materialize_session_image(
            payload.session_id, target.version, target.image_url_or_base64
        )
        target.image_url_or_base64 = data_url
        target.local_image_path = local_path

    state.approved_image_id = target.image_id
    state.approved_image_version = target.version
    state.approved_image_local_path = target.local_image_path
    # Approve screen entry point for TripoSR 2D -> 3D conversion.
    if state.step < 6:
        state.step = 6
    store.save(state)
    return VersionApproveResponse(
        message=f"Version v{target.version} approved for 3D preview conversion.",
        approved_version=target.version,
    )


@app.post("/api/preview3d/generate", response_model=Preview3DGenerateResponse)
async def generate_preview_3d(payload: Preview3DGenerateRequest, request: Request) -> Preview3DGenerateResponse:
    limiter.check(request, "preview3d-generate")
    state = store.get_or_create(payload.session_id)
    if not state.approved_image_local_path:
        raise HTTPException(status_code=400, detail="Approve a version first before generating 3D preview.")

    input_path = state.approved_image_local_path
    if not Path(input_path).exists():
        raise HTTPException(status_code=404, detail="Approved source image file is missing on disk.")

    preview_path = _run_triposr(input_path, payload.session_id)
    rel = Path(preview_path).resolve().relative_to(Path(settings.triposr_output_dir).resolve())
    rel_str = str(rel).replace("\\", "/")
    preview_file = f"/preview-3d/{rel_str}"
    state.preview_3d_file = preview_file
    if state.step < 7:
        state.step = 7
    store.save(state)
    return Preview3DGenerateResponse(
        message=f"3D preview generated from approved version v{state.approved_image_version}.",
        preview_file=preview_file,
    )


@app.post("/api/baseline/skip", response_model=BaselineSkipResponse)
async def skip_baseline(payload: BaselineSkipRequest, request: Request) -> BaselineSkipResponse:
    limiter.check(request, "baseline-skip")
    state = store.get_or_create(payload.session_id)
    state.baseline_asset = None
    if state.step < 4:
        state.step = 4
    store.save(state)
    return BaselineSkipResponse(message="Proceeding without baseline selection.", step=state.step)


@app.post("/api/session/clear", response_model=SessionClearResponse)
async def clear_session(payload: SessionClearRequest, request: Request) -> SessionClearResponse:
    limiter.check(request, "session-clear")
    reset_state = store.get_or_create(payload.session_id)
    # Reset workflow conversation/spec/images/3D preview while keeping session id continuity.
    reset_state.step = 1
    reset_state.spec = reset_state.spec.__class__()
    reset_state.missing_fields = []
    reset_state.required_questions = []
    reset_state.baseline_decision = None
    reset_state.baseline_decision_done = False
    reset_state.baseline_matches = []
    reset_state.baseline_asset = None
    reset_state.images = []
    reset_state.approved_image_id = None
    reset_state.approved_image_version = None
    reset_state.approved_image_local_path = None
    reset_state.lock_question_asked = False
    reset_state.lock_confirmed = False
    reset_state.design_summary = None
    reset_state.preview_3d_file = None
    reset_state.history = []
    store.save(reset_state)
    return SessionClearResponse(message="Session state cleared.")


@app.get("/api/session/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, request: Request) -> SessionResponse:
    limiter.check(request, "session")
    state: dict[str, Any] = store.as_dict(session_id)
    return SessionResponse(state=state)


app.mount("/asset-files", StaticFiles(directory=settings.assets_dir), name="asset-files")
app.mount("/preview-3d", StaticFiles(directory=settings.triposr_output_dir), name="preview-3d")
app.mount("/", StaticFiles(directory="static", html=True), name="static")
