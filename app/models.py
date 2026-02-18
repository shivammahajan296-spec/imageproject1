from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


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
    lock_question_asked: bool = False
    lock_confirmed: bool = False
    cadquery_code: str | None = None
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


class CadGenerateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)


class CadGenerateResponse(BaseModel):
    cadquery_code: str
    design_summary: str


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
