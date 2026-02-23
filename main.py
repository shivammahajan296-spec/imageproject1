from __future__ import annotations

import base64
import hashlib
import io
import imghdr
import json
import logging
import mimetypes
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
    CacheClearResponse,
    EditRecommendationsResponse,
    BriefUploadResponse,
    CadModelGenerateRequest,
    CadModelGenerateResponse,
    CadModelFixRequest,
    CadModelRunCodeRequest,
    CadSheetGenerateRequest,
    CadSheetGenerateResponse,
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
CACHE_DIR = Path(settings.cache_dir)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
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
    "Please approve a version from Version History, then generate the STEP CAD model.",
}
BASELINE_SEARCH_MSG = "Searching for a similar baseline design…"
BASELINE_NEW_MSG = "No close baseline found. Creating a new concept."
SESSION_IMAGE_DIR = Path(settings.session_images_dir)
SESSION_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
CAD_RUN_DIR = SESSION_IMAGE_DIR / "cad_runs"
CAD_RUN_DIR.mkdir(parents=True, exist_ok=True)
CAD_LLM_SYSTEM_PROMPT = (
    "You are a senior mechanical CAD engineer and geometric reconstruction specialist.\n\n"
    "Return ONLY Python code for CadQuery that creates closed BREP solids and exports a STEP file.\n"
    "No markdown fences, no explanation, no STL, no mesh operations.\n"
    "Use mm units, realistic manufacturable geometry, and keep script deterministic.\n"
    "Script must define geometry variables and call cq.exporters.export(..., <step_path>)."
)


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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _cache_file(kind: str, key: str) -> Path:
    safe_kind = re.sub(r"[^a-zA-Z0-9._-]", "_", kind)
    safe_key = re.sub(r"[^a-zA-Z0-9._-]", "_", key)
    return CACHE_DIR / f"{safe_kind}_{safe_key}.json"


def _cache_json_get(kind: str, key: str) -> dict[str, Any] | None:
    path = _cache_file(kind, key)
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _cache_json_put(kind: str, key: str, payload: dict[str, Any]) -> None:
    _cache_file(kind, key).write_text(json.dumps(payload), encoding="utf-8")


def _cache_get(kind: str, key: str) -> dict[str, str] | None:
    payload = _cache_json_get(kind, key)
    if not payload:
        return None
    image_id = str(payload.get("image_id", "")).strip()
    image_data_url = str(payload.get("image_data_url", "")).strip()
    if not image_data_url:
        return None
    return {"image_id": image_id or f"cached-{kind}-{key[:8]}", "image_data_url": image_data_url}


def _cache_put(kind: str, key: str, image_id: str, image_data_url: str) -> None:
    payload = {"image_id": image_id, "image_data_url": image_data_url}
    _cache_json_put(kind, key, payload)


def _cache_clear_all() -> int:
    removed = 0
    for p in CACHE_DIR.rglob("*"):
        if p.is_file():
            p.unlink(missing_ok=True)
            removed += 1
    for p in CAD_RUN_DIR.rglob("*"):
        if p.is_file():
            p.unlink(missing_ok=True)
            removed += 1
    # Cleanup empty run folders after file removal.
    for d in sorted(CAD_RUN_DIR.rglob("*"), reverse=True):
        if d.is_dir():
            try:
                d.rmdir()
            except OSError:
                pass
    return removed


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


def _extract_python_code(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        match = re.search(r"```(?:python)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
        if match:
            raw = match.group(1).strip()
    return raw


def _validate_cad_script(script: str) -> None:
    banned_tokens = [
        "import os",
        "import sys",
        "import subprocess",
        "import socket",
        "import requests",
        "eval(",
        "exec(",
        "open(",
        "__import__",
    ]
    lowered = script.lower()
    for token in banned_tokens:
        if token in lowered:
            raise HTTPException(status_code=400, detail=f"Generated CAD script contains blocked token: {token}")
    if "import cadquery" not in lowered and "from cadquery" not in lowered:
        raise HTTPException(status_code=400, detail="Generated CAD script is missing CadQuery import.")


def _resolve_relative_public_file(url_path: str) -> Path:
    rel = url_path.removeprefix("/session-files/")
    return (SESSION_IMAGE_DIR / rel).resolve()


def _run_generated_cad_script(script_text: str, session_id: str) -> tuple[str, str]:
    run_dir = CAD_RUN_DIR / f"{_safe_session_key(session_id)}-{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_dir = run_dir.resolve()
    script_path = run_dir / "generated_cad.py"
    script_path.write_text(script_text, encoding="utf-8")
    script_path = script_path.resolve()

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(run_dir),
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise HTTPException(status_code=502, detail=f"CAD script execution failed: {err[:800]}")

    step_candidates = list(run_dir.rglob("*.step")) + list(run_dir.rglob("*.stp"))
    if not step_candidates:
        raise HTTPException(
            status_code=502, detail="CAD script ran but no STEP file was produced. Ensure exporters.export outputs .step."
        )

    step_path = max(step_candidates, key=lambda p: p.stat().st_mtime)
    return str(script_path.resolve()), str(step_path.resolve())


def _cad_failure_response(
    state,
    message: str,
    cad_code: str,
    error_detail: str,
    cached: bool = False,
    attempts: int | None = None,
) -> CadModelGenerateResponse:
    state.cad_model_code = cad_code
    state.cad_model_last_error = error_detail
    state.cad_model_code_path = None
    state.cad_step_file = None
    store.save(state)
    return CadModelGenerateResponse(
        message=message,
        success=False,
        cad_code=cad_code,
        code_file=None,
        step_file=None,
        error_detail=error_detail,
        cached=cached,
        attempts=attempts,
    )


def _execute_and_persist_cad_code(state, session_id: str, cad_code: str) -> tuple[bool, str | None, str | None, str | None]:
    try:
        _validate_cad_script(cad_code)
    except HTTPException as exc:
        return False, None, None, str(exc.detail)
    try:
        script_path, step_path = _run_generated_cad_script(cad_code, session_id)
    except HTTPException as exc:
        return False, None, None, str(exc.detail)

    code_rel = "/" + str(Path(script_path).resolve().relative_to(SESSION_IMAGE_DIR.resolve())).replace("\\", "/")
    step_rel = "/" + str(Path(step_path).resolve().relative_to(SESSION_IMAGE_DIR.resolve())).replace("\\", "/")
    code_file = f"/session-files{code_rel}"
    step_file = f"/session-files{step_rel}"

    state.cad_model_code = cad_code
    state.cad_model_last_error = None
    state.cad_model_code_path = code_file
    state.cad_step_file = step_file
    if state.step < 7:
        state.step = 7
    store.save(state)
    return True, code_file, step_file, None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> FileResponse:
    return FileResponse("static/index.html")


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

    prompt_key = re.sub(r"\s+", " ", payload.prompt.strip())
    cache_key = _sha256_text(prompt_key)
    cached = _cache_get("concept", cache_key)
    if cached:
        generated = {"image_id": cached["image_id"], "image_url_or_base64": cached["image_data_url"]}
    else:
        generated = await straive.image_generate(payload.prompt, api_key_override=req_api_key)
    version = len(state.images) + 1
    image_data_url, local_path = await _materialize_session_image(
        payload.session_id, version, generated["image_url_or_base64"], req_api_key=req_api_key
    )
    if not cached:
        _cache_put("concept", cache_key, generated["image_id"] or str(uuid.uuid4()), image_data_url)
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
    state.cad_sheet_prompt = None
    state.cad_sheet_image_id = None
    state.cad_sheet_image_url_or_base64 = None
    state.cad_sheet_image_local_path = None
    state.cad_model_prompt = None
    state.cad_model_code = None
    state.cad_model_last_error = None
    state.cad_model_code_path = None
    state.cad_step_file = None

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
    source_blob, _ = await _resolve_image_bytes(latest_ref, req_api_key=req_api_key)
    normalized_instruction = re.sub(r"\s+", " ", payload.instruction_prompt.strip())
    edit_key = _sha256_text(f"{_sha256_bytes(source_blob)}::{normalized_instruction}")
    cached = _cache_get("edit", edit_key)
    if cached:
        edited = {"image_id": cached["image_id"], "image_url_or_base64": cached["image_data_url"]}
    else:
        try:
            edited = await straive.image_edit(latest_ref, payload.instruction_prompt, api_key_override=req_api_key)
        except Exception as exc:
            logger.error("Image edit failed. session=%s error=%s", payload.session_id, exc)
            raise HTTPException(status_code=502, detail=f"Image edit failed: {exc}") from exc
    version = len(state.images) + 1
    image_data_url, local_path = await _materialize_session_image(
        payload.session_id, version, edited["image_url_or_base64"], req_api_key=req_api_key
    )
    if not cached:
        _cache_put("edit", edit_key, edited["image_id"] or str(uuid.uuid4()), image_data_url)
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
    state.cad_sheet_prompt = None
    state.cad_sheet_image_id = None
    state.cad_sheet_image_url_or_base64 = None
    state.cad_sheet_image_local_path = None
    state.cad_model_prompt = None
    state.cad_model_code = None
    state.cad_model_last_error = None
    state.cad_model_code_path = None
    state.cad_step_file = None

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
    state.cad_sheet_prompt = None
    state.cad_sheet_image_id = None
    state.cad_sheet_image_url_or_base64 = None
    state.cad_sheet_image_local_path = None
    state.cad_model_prompt = None
    state.cad_model_code = None
    state.cad_model_last_error = None
    state.cad_model_code_path = None
    state.cad_step_file = None
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
    state.cad_sheet_image_id = None
    state.cad_sheet_image_url_or_base64 = None
    state.cad_sheet_image_local_path = None
    state.cad_model_prompt = None
    state.cad_model_code = None
    state.cad_model_last_error = None
    state.cad_model_code_path = None
    state.cad_step_file = None
    # Approve screen entry point for STEP CAD generation.
    if state.step < 6:
        state.step = 6
    store.save(state)
    return VersionApproveResponse(
        message=f"Version v{target.version} approved for STEP CAD generation.",
        approved_version=target.version,
    )


@app.post("/api/cad-sheet/generate", response_model=CadSheetGenerateResponse)
async def generate_cad_sheet(payload: CadSheetGenerateRequest, request: Request) -> CadSheetGenerateResponse:
    limiter.check(request, "cad-sheet-generate")
    state = store.get_or_create(payload.session_id)
    req_api_key = _request_api_key(request)

    if not state.approved_image_local_path:
        raise HTTPException(status_code=400, detail="Approve a version first before generating CAD drawing sheet.")

    input_path = state.approved_image_local_path
    if not Path(input_path).exists():
        raise HTTPException(status_code=404, detail="Approved source image file is missing on disk.")

    approved_blob = Path(input_path).read_bytes()
    normalized_cad_prompt = re.sub(r"\s+", " ", payload.prompt.strip())
    cad_key = _sha256_text(f"{_sha256_bytes(approved_blob)}::{normalized_cad_prompt}")
    cached = _cache_get("cadsheet", cad_key)
    if cached:
        edited = {"image_id": cached["image_id"], "image_url_or_base64": cached["image_data_url"]}
    else:
        edited = await straive.image_edit(input_path, payload.prompt, api_key_override=req_api_key)
    blob, mime_type = await _resolve_image_bytes(edited["image_url_or_base64"], req_api_key=req_api_key)
    ext = mimetypes.guess_extension(mime_type) or ".png"
    sess_dir = SESSION_IMAGE_DIR / _safe_session_key(payload.session_id)
    sess_dir.mkdir(parents=True, exist_ok=True)
    local_path = sess_dir / f"cad_sheet_{uuid.uuid4().hex[:8]}{ext}"
    local_path.write_bytes(blob)
    data_url = f"data:{mime_type};base64,{base64.b64encode(blob).decode('utf-8')}"
    if not cached:
        _cache_put("cadsheet", cad_key, edited.get("image_id") or f"cad-sheet-{uuid.uuid4().hex[:8]}", data_url)

    state.cad_sheet_prompt = payload.prompt
    state.cad_sheet_image_id = edited.get("image_id") or f"cad-sheet-{uuid.uuid4().hex[:8]}"
    state.cad_sheet_image_url_or_base64 = data_url
    state.cad_sheet_image_local_path = str(local_path.resolve())
    store.save(state)
    return CadSheetGenerateResponse(
        message=f"CAD drawing sheet generated from approved version v{state.approved_image_version}.",
        image_id=state.cad_sheet_image_id,
        image_url_or_base64=state.cad_sheet_image_url_or_base64,
    )


@app.post("/api/cad/model/generate", response_model=CadModelGenerateResponse)
async def generate_cad_model(payload: CadModelGenerateRequest, request: Request) -> CadModelGenerateResponse:
    limiter.check(request, "cad-model-generate")
    state = store.get_or_create(payload.session_id)
    req_api_key = _request_api_key(request)

    if not state.approved_image_local_path:
        raise HTTPException(status_code=400, detail="Approve a version first before generating CAD model.")

    source_path = Path(state.approved_image_local_path)
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Approved source image file is missing on disk.")

    approved_blob = source_path.read_bytes()
    approved_mime = _detect_mime_from_bytes(approved_blob, hinted=mimetypes.guess_type(str(source_path))[0])
    normalized_prompt = re.sub(r"\s+", " ", payload.prompt.strip())
    cad_cache_key = _sha256_text(f"{_sha256_bytes(approved_blob)}::{normalized_prompt}")
    cached_payload = _cache_json_get("cadstep", cad_cache_key)
    if cached_payload:
        code_file_cached = str(cached_payload.get("code_file", "")).strip()
        step_file_cached = str(cached_payload.get("step_file", "")).strip()
        cad_code_cached = str(cached_payload.get("cad_code", "")).strip()
        if code_file_cached and step_file_cached and cad_code_cached:
            code_path = _resolve_relative_public_file(code_file_cached)
            step_path = _resolve_relative_public_file(step_file_cached)
            if code_path.exists() and step_path.exists():
                state.cad_model_prompt = payload.prompt
                state.cad_model_code = cad_code_cached
                state.cad_model_last_error = None
                state.cad_model_code_path = code_file_cached
                state.cad_step_file = step_file_cached
                if state.step < 7:
                    state.step = 7
                store.save(state)
                return CadModelGenerateResponse(
                    message=f"CAD model loaded from cache for approved version v{state.approved_image_version}.",
                    success=True,
                    cad_code=cad_code_cached,
                    code_file=code_file_cached,
                    step_file=step_file_cached,
                    error_detail=None,
                    cached=True,
                )

    user_prompt = (
        payload.prompt.strip()
        + "\n\nINPUT CONTEXT:\n"
        + f"- Approved image path: {source_path}\n"
        + f"- Session spec summary: {spec_summary(state.spec)}\n"
        + "- Output a single executable Python script only."
    )
    llm_text = await straive.cad_codegen(
        system_prompt=CAD_LLM_SYSTEM_PROMPT,
        user_message=user_prompt,
        api_key_override=req_api_key,
        image_bytes=approved_blob,
        image_mime_type=approved_mime,
    )
    if not llm_text or not llm_text.strip():
        return _cad_failure_response(
            state=state,
            message="CAD generation failed: LLM returned empty output.",
            cad_code="",
            error_detail="LLM returned empty CAD script output.",
            cached=False,
        )

    cad_code = _extract_python_code(llm_text)
    ok, code_file, step_file, err = _execute_and_persist_cad_code(state, payload.session_id, cad_code)
    if not ok:
        return _cad_failure_response(
            state=state,
            message="CAD execution failed. Fix code and retry.",
            cad_code=cad_code,
            error_detail=err or "Unknown CAD execution failure.",
            cached=False,
        )

    _cache_json_put(
        "cadstep",
        cad_cache_key,
        {
            "cad_code": cad_code,
            "code_file": code_file,
            "step_file": step_file,
        },
    )
    state.cad_model_prompt = payload.prompt
    store.save(state)

    return CadModelGenerateResponse(
        message=f"CAD STEP model generated from approved version v{state.approved_image_version}.",
        success=True,
        cad_code=cad_code,
        code_file=code_file,
        step_file=step_file,
        error_detail=None,
        cached=False,
    )


@app.post("/api/cad/model/run-code", response_model=CadModelGenerateResponse)
async def run_cad_model_code(payload: CadModelRunCodeRequest, request: Request) -> CadModelGenerateResponse:
    limiter.check(request, "cad-model-run-code")
    state = store.get_or_create(payload.session_id)
    cad_code = (payload.cad_code or "").strip()
    if not cad_code:
        return _cad_failure_response(
            state=state,
            message="No CAD code provided.",
            cad_code="",
            error_detail="CAD code is empty.",
            cached=False,
        )

    ok, code_file, step_file, err = _execute_and_persist_cad_code(state, payload.session_id, cad_code)
    if not ok:
        return _cad_failure_response(
            state=state,
            message="CAD execution failed. Fix code and retry.",
            cad_code=cad_code,
            error_detail=err or "Unknown CAD execution failure.",
            cached=False,
        )

    return CadModelGenerateResponse(
        message="CAD code executed successfully and STEP generated.",
        success=True,
        cad_code=cad_code,
        code_file=code_file,
        step_file=step_file,
        error_detail=None,
        cached=False,
    )


@app.post("/api/cad/model/fix-code", response_model=CadModelGenerateResponse)
async def fix_cad_model_code(payload: CadModelFixRequest, request: Request) -> CadModelGenerateResponse:
    limiter.check(request, "cad-model-fix-code")
    state = store.get_or_create(payload.session_id)
    req_api_key = _request_api_key(request)

    code = (payload.cad_code or "").strip()
    if not code:
        return _cad_failure_response(
            state=state,
            message="No CAD code provided.",
            cad_code="",
            error_detail="CAD code is empty.",
            attempts=0,
        )

    last_error = (payload.error_detail or state.cad_model_last_error or "").strip()
    attempts_done = 0
    for _ in range(payload.max_attempts):
        attempts_done += 1
        ok, code_file, step_file, err = _execute_and_persist_cad_code(state, payload.session_id, code)
        if ok:
            return CadModelGenerateResponse(
                message=f"CAD code fixed and STEP generated in {attempts_done} attempt(s).",
                success=True,
                cad_code=code,
                code_file=code_file,
                step_file=step_file,
                error_detail=None,
                cached=False,
                attempts=attempts_done,
            )

        last_error = err or last_error or "Unknown CAD execution failure."
        fix_prompt = (
            "Fix this CadQuery Python script so it executes successfully and exports at least one .step file.\n"
            "Return only corrected Python code.\n\n"
            f"Execution error:\n{last_error}\n\n"
            "Current code:\n"
            f"{code}"
        )
        llm_text = await straive.cad_codegen(
            system_prompt=CAD_LLM_SYSTEM_PROMPT,
            user_message=fix_prompt,
            api_key_override=req_api_key,
            image_bytes=None,
            image_mime_type=None,
        )
        if not llm_text or not llm_text.strip():
            break
        code = _extract_python_code(llm_text)

    return _cad_failure_response(
        state=state,
        message=f"Auto-fix did not produce a STEP file after {attempts_done} attempt(s).",
        cad_code=code,
        error_detail=last_error or "Auto-fix failed without error output.",
        attempts=attempts_done,
    )


@app.post("/api/cache/clear", response_model=CacheClearResponse)
async def clear_cache(request: Request) -> CacheClearResponse:
    limiter.check(request, "cache-clear")
    removed = _cache_clear_all()
    return CacheClearResponse(message="Cache cleared.", removed_files=removed)


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
    # Reset workflow conversation/spec/images/CAD outputs while keeping session id continuity.
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
    reset_state.cad_sheet_prompt = None
    reset_state.cad_sheet_image_id = None
    reset_state.cad_sheet_image_url_or_base64 = None
    reset_state.cad_sheet_image_local_path = None
    reset_state.cad_model_prompt = None
    reset_state.cad_model_code = None
    reset_state.cad_model_last_error = None
    reset_state.cad_model_code_path = None
    reset_state.cad_step_file = None
    reset_state.lock_question_asked = False
    reset_state.lock_confirmed = False
    reset_state.design_summary = None
    reset_state.history = []
    store.save(reset_state)
    return SessionClearResponse(message="Session state cleared.")


@app.get("/api/session/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, request: Request) -> SessionResponse:
    limiter.check(request, "session")
    state: dict[str, Any] = store.as_dict(session_id)
    return SessionResponse(state=state)


app.mount("/asset-files", StaticFiles(directory=settings.assets_dir), name="asset-files")
app.mount("/session-files", StaticFiles(directory=str(SESSION_IMAGE_DIR)), name="session-files")
app.mount("/static", StaticFiles(directory="static"), name="static")
