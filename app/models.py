from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

#shivam
PackagingType = Literal["jar", "bottle", "cap", "container", "cosmetic_jar"]
MaterialType = Literal["pp", "pet", "hdpe", "glass", "other"]


class DesignSpec(BaseModel):
    product_type: str | None = None
    size_or_volume: str | None = None
    intended_material: str | None = None
    closure_type: str | None = None
    design_style: str | None = None
    dimensions: dict[str, float] = Field(default_factory=dict)
    process_notes: str | None = None


class ImageVersion(BaseModel):
    image_id: str
    image_url_or_base64: str
    version: int
    prompt: str
    local_image_path: str | None = None


class SessionState(BaseModel):
    session_id: str
    step: int = 1
    spec: DesignSpec = Field(default_factory=DesignSpec)
    missing_fields: list[str] = Field(default_factory=list)
    required_questions: list[str] = Field(default_factory=list)
    baseline_decision: str | None = None
    baseline_decision_done: bool = False
    baseline_matches: list[dict[str, Any]] = Field(default_factory=list)
    baseline_asset: dict[str, Any] | None = None
    images: list[ImageVersion] = Field(default_factory=list)
    approved_image_id: str | None = None
    approved_image_version: int | None = None
    approved_image_local_path: str | None = None
    cad_sheet_prompt: str | None = None
    cad_sheet_image_id: str | None = None
    cad_sheet_image_url_or_base64: str | None = None
    cad_sheet_image_local_path: str | None = None
    cad_model_prompt: str | None = None
    cad_model_provider: str | None = None
    cad_model_code: str | None = None
    cad_model_last_error: str | None = None
    cad_model_code_path: str | None = None
    cad_step_file: str | None = None
    lock_question_asked: bool = False
    lock_confirmed: bool = False
    design_summary: str | None = None
    history: list[dict[str, str]] = Field(default_factory=list)


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)
    user_message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    assistant_message: str
    step: int
    spec_summary: str
    required_questions: list[str] = Field(default_factory=list)
    can_generate_image: bool
    can_iterate_image: bool
    can_lock: bool
    can_generate_cad: bool


class ImageGenerateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=3, max_length=2000)


class ImageEditRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)
    image_id: str = Field(min_length=1, max_length=256)
    instruction_prompt: str = Field(min_length=3, max_length=2000)


class ImageResponse(BaseModel):
    image_id: str
    image_url_or_base64: str
    version: int


class JobStartResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    message: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class SessionResponse(BaseModel):
    state: dict[str, Any]


class AssetIndexRequest(BaseModel):
    force_reindex: bool = False


class AssetIndexResponse(BaseModel):
    indexed_count: int
    total_assets: int


class EditRecommendationsResponse(BaseModel):
    count: int
    recommendations: list[str] = Field(default_factory=list)


class BaselineAdoptRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)
    asset_rel_path: str = Field(min_length=1, max_length=500)


class BaselineSkipRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)


class BaselineSkipResponse(BaseModel):
    message: str
    step: int


class SessionClearRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)


class SessionClearResponse(BaseModel):
    message: str


class CacheClearResponse(BaseModel):
    message: str
    removed_files: int


class AssetCatalogItem(BaseModel):
    asset_rel_path: str
    filename: str
    product_type: str | None = None
    material: str | None = None
    closure_type: str | None = None
    design_style: str | None = None
    size_or_volume: str | None = None
    tags: str | None = None
    summary: str | None = None
    metadata_json: dict[str, Any] | None = None
    updated_at: str


class AssetCatalogResponse(BaseModel):
    total: int
    items: list[AssetCatalogItem] = Field(default_factory=list)


class BriefUploadResponse(BaseModel):
    message: str
    step: int
    spec_summary: str
    required_questions: list[str] = Field(default_factory=list)


class VersionApproveRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1)


class VersionApproveResponse(BaseModel):
    message: str
    approved_version: int


class CadSheetGenerateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=10, max_length=8000)


class CadSheetGenerateResponse(BaseModel):
    message: str
    image_id: str
    image_url_or_base64: str


class CadModelGenerateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=20, max_length=12000)
    provider: str | None = None


class CadModelRunCodeRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)
    cad_code: str = Field(min_length=20, max_length=200000)
    prompt: str | None = None
    provider: str | None = None


class CadModelFixRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)
    cad_code: str = Field(min_length=20, max_length=200000)
    error_detail: str | None = None
    prompt: str | None = None
    provider: str | None = None


class CadModelGenerateResponse(BaseModel):
    message: str
    success: bool = True
    cad_code: str = ""
    code_file: str | None = None
    step_file: str | None = None
    error_detail: str | None = None
    cached: bool = False
    attempts: int | None = None
