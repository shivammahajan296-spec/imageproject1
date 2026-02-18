from __future__ import annotations

import base64
import logging
import mimetypes
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.asset_search import AssetCatalog
from app.cad import CadGenerationError, generate_cadquery_code
from app.config import load_settings
from app.models import (
    AssetIndexRequest,
    AssetIndexResponse,
    BaselineAdoptRequest,
    CadGenerateRequest,
    CadGenerateResponse,
    ChatRequest,
    ChatResponse,
    EditRecommendationsResponse,
    ProgressResponse,
    SaveProgressRequest,
    SaveProgressResponse,
    ImageEditRequest,
    ImageGenerateRequest,
    ImageResponse,
    ImageVersion,
    SessionResponse,
)
from app.rate_limit import SimpleRateLimiter
from app.recommendations import build_edit_recommendations
from app.storage import SessionStore
from app.straive_client import StraiveClient
from app.workflow import WORKFLOW_SYSTEM_PROMPT, handle_chat_turn, spec_summary

settings = load_settings()
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
    "Do you want to lock this design and generate the 3D CAD (STEP) file?",
}
BASELINE_SEARCH_MSG = "Searching for a similar baseline design…"
BASELINE_NEW_MSG = "No close baseline found. Creating a new concept."


def _request_api_key(request: Request) -> str | None:
    value = request.headers.get("X-Straive-Api-Key", "").strip()
    return value or None


def _normalize_image_ref_for_edit(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return raw
    if raw.startswith("http://") or raw.startswith("https://") or raw.startswith("data:image"):
        return raw
    # Straive may return bare base64 for generated images; normalize to data URL for edit calls.
    return f"data:image/png;base64,{raw}"


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
        can_generate_cad=flags["can_generate_cad"],
    )


@app.post("/api/assets/index", response_model=AssetIndexResponse)
async def index_assets(payload: AssetIndexRequest, request: Request) -> AssetIndexResponse:
    limiter.check(request, "assets-index")
    req_api_key = _request_api_key(request)
    indexed_count, total_assets = await asset_catalog.index_assets(
        straive=straive, force_reindex=payload.force_reindex, api_key_override=req_api_key
    )
    return AssetIndexResponse(indexed_count=indexed_count, total_assets=total_assets)


@app.get("/api/recommendations/{session_id}", response_model=EditRecommendationsResponse)
async def get_recommendations(session_id: str, request: Request) -> EditRecommendationsResponse:
    limiter.check(request, "recommendations")
    state = store.get_or_create(session_id)
    recs = build_edit_recommendations(state.spec)
    return EditRecommendationsResponse(count=len(recs), recommendations=recs)


@app.post("/api/session/save-progress", response_model=SaveProgressResponse)
async def save_progress(payload: SaveProgressRequest, request: Request) -> SaveProgressResponse:
    limiter.check(request, "save-progress")
    checkpoint_id, saved_at = store.save_checkpoint(payload.session_id, payload.label)
    return SaveProgressResponse(checkpoint_id=checkpoint_id, saved_at=saved_at)


@app.get("/api/progress", response_model=ProgressResponse)
async def get_progress(request: Request) -> ProgressResponse:
    limiter.check(request, "progress")
    snapshot = store.progress_snapshot()
    return ProgressResponse(
        in_progress=snapshot["in_progress"],
        approved_designs=snapshot["approved_designs"],
        checkpoints=snapshot["checkpoints"],
    )


@app.post("/api/image/generate", response_model=ImageResponse)
async def image_generate(payload: ImageGenerateRequest, request: Request) -> ImageResponse:
    limiter.check(request, "image-generate")
    state = store.get_or_create(payload.session_id)
    req_api_key = _request_api_key(request)

    if state.step < 3:
        raise HTTPException(status_code=400, detail="Workflow has not reached STEP 3.")

    generated = await straive.image_generate(payload.prompt, api_key_override=req_api_key)
    version = len(state.images) + 1
    image = ImageVersion(
        image_id=generated["image_id"] or str(uuid.uuid4()),
        image_url_or_base64=generated["image_url_or_base64"],
        version=version,
        prompt=payload.prompt,
    )
    state.images.append(image)

    if state.step < 4:
        state.step = 4

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

    if state.step < 4 or not state.images:
        raise HTTPException(status_code=400, detail="Workflow has not reached STEP 4 with a reference image.")
    if state.lock_confirmed:
        raise HTTPException(status_code=400, detail="Design is locked. Iteration is not allowed.")

    # Always edit the latest session visual so iteration is continuous from the current reference.
    latest_ref = state.images[-1].image_url_or_base64 if state.images else payload.image_id
    latest_ref = _normalize_image_ref_for_edit(latest_ref)
    edited = await straive.image_edit(latest_ref, payload.instruction_prompt, api_key_override=req_api_key)
    version = len(state.images) + 1
    image = ImageVersion(
        image_id=edited["image_id"] or str(uuid.uuid4()),
        image_url_or_base64=edited["image_url_or_base64"],
        version=version,
        prompt=payload.instruction_prompt,
    )
    state.images.append(image)

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
    )
    state.images.append(image)
    if state.step < 4:
        state.step = 4
    store.save(state)
    return ImageResponse(
        image_id=image.image_id,
        image_url_or_base64=image.image_url_or_base64,
        version=image.version,
    )


@app.post("/api/cad/generate", response_model=CadGenerateResponse)
async def cad_generate(payload: CadGenerateRequest, request: Request) -> CadGenerateResponse:
    limiter.check(request, "cad-generate")
    state = store.get_or_create(payload.session_id)

    if not state.lock_confirmed or state.step < 6:
        raise HTTPException(status_code=400, detail="Design must be locked at STEP 5 before CAD generation.")

    try:
        code, summary = generate_cadquery_code(state.spec)
    except CadGenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    state.cadquery_code = code
    state.design_summary = summary
    state.step = 7
    store.save(state)

    return CadGenerateResponse(cadquery_code=code, design_summary=summary)


@app.get("/api/session/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, request: Request) -> SessionResponse:
    limiter.check(request, "session")
    state: dict[str, Any] = store.as_dict(session_id)
    return SessionResponse(state=state)


app.mount("/asset-files", StaticFiles(directory=settings.assets_dir), name="asset-files")
app.mount("/", StaticFiles(directory="static", html=True), name="static")
