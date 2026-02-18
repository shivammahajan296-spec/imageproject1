from __future__ import annotations

import re
from typing import Any

from app.models import DesignSpec, SessionState

WORKFLOW_SYSTEM_PROMPT = """
You are a senior packaging engineer assistant for "AI-Powered Intelligent Pack Design".
Follow this strict state machine and never skip steps.

STEP 1: Understand user intent. Collect product type, approx size/volume, intended material, closure type, design style.
Ask minimal clarifying questions only for missing critical fields.

STEP 2: Normalize into structured spec internally. Never show JSON unless user asks.
Never guess dimensions. If unknown, ask clearly.

STEP 3: Baseline search decision. Say exactly one of:
"Searching for a similar baseline design…"
or
"No close baseline found. Creating a new concept."
Only decision output for this step.

STEP 4: 2D design iteration only. Use existing 2D visual as reference.
For requested changes, refine consistently and do not restart design.
Do not discuss 3D generation in this step.

STEP 5: Design approval confirmation. Ask user to approve a version from Edit Studio before 3D generation.

STEP 6: 3D generation readiness. Once a version is approved, guide the user to run TripoSR conversion.

STEP 7: Final output. Confirm 3D preview is generated and available in the viewer/download link.

Behavior:
- Act as a senior packaging engineer, not a generic chatbot.
- Never hallucinate dimensions.
- Keep questions minimal and focused.
- Never jump ahead of current workflow step.
""".strip()

SPEC_FIELDS = ["product_type", "size_or_volume", "intended_material", "closure_type", "design_style"]

PRODUCT_PATTERNS = [
    (r"\bcosmetic\s+jar\b", "cosmetic_jar"),
    (r"\bjar\b", "jar"),
    (r"\bbottle\b", "bottle"),
    (r"\bcontainer\b", "container"),
    (r"\bcap\b", "cap"),
]
MATERIAL_HINTS = ["pp", "pet", "hdpe", "glass", "aluminum", "paper", "other"]
CLOSURE_HINTS = ["screw", "flip top", "snap", "pump", "press", "lid", "cork"]
STYLE_HINTS = ["minimal", "luxury", "matte", "gloss", "premium", "playful", "clinical"]

CONFIRM_WORDS = {"yes", "confirm", "lock", "proceed", "go ahead", "approve", "confirmed"}



def _extract_dimensions(message: str) -> dict[str, float]:
    dims: dict[str, float] = {}
    patterns = {
        "outer_diameter_mm": r"outer\s*diameter\s*(?:=|:)?\s*(\d+(?:\.\d+)?)\s*mm",
        "height_mm": r"(?:body\s*)?height\s*(?:=|:)?\s*(\d+(?:\.\d+)?)\s*mm",
        "wall_thickness_mm": r"wall\s*thickness\s*(?:=|:)?\s*(\d+(?:\.\d+)?)\s*mm",
        "cap_height_mm": r"cap\s*height\s*(?:=|:)?\s*(\d+(?:\.\d+)?)\s*mm",
        "body_diameter_mm": r"body\s*diameter\s*(?:=|:)?\s*(\d+(?:\.\d+)?)\s*mm",
        "body_height_mm": r"body\s*height\s*(?:=|:)?\s*(\d+(?:\.\d+)?)\s*mm",
        "neck_diameter_mm": r"neck\s*diameter\s*(?:=|:)?\s*(\d+(?:\.\d+)?)\s*mm",
        "neck_height_mm": r"neck\s*height\s*(?:=|:)?\s*(\d+(?:\.\d+)?)\s*mm",
    }
    lower = message.lower()
    for key, pat in patterns.items():
        m = re.search(pat, lower)
        if m:
            dims[key] = float(m.group(1))
    return dims


def update_spec_from_message(spec: DesignSpec, message: str) -> None:
    lower = message.lower()

    has_dim_tokens = any(x in lower for x in ["diameter", "height", "thickness", "mm"])
    type_context = any(x in lower for x in ["product type", "packaging type", "i need", "i want", "make a"])
    detected_product: str | None = None
    for pattern, product in PRODUCT_PATTERNS:
        if re.search(pattern, lower):
            detected_product = product
            break

    # Prevent dimension-only messages (e.g., "cap height 14 mm") from overwriting product type to "cap".
    if detected_product:
        if detected_product == "cap" and "cap height" in lower and spec.product_type:
            detected_product = None
        elif has_dim_tokens and spec.product_type and not type_context:
            detected_product = None

    if detected_product:
        spec.product_type = detected_product

    if any(x in lower for x in MATERIAL_HINTS):
        for hint in MATERIAL_HINTS:
            if hint in lower:
                spec.intended_material = hint
                break

    if any(x in lower for x in CLOSURE_HINTS):
        for hint in CLOSURE_HINTS:
            if hint in lower:
                spec.closure_type = hint
                break

    if any(x in lower for x in STYLE_HINTS):
        for hint in STYLE_HINTS:
            if hint in lower:
                spec.design_style = hint
                break

    vol_match = re.search(r"(\d+(?:\.\d+)?)\s*(ml|l|cc)", lower)
    if vol_match:
        spec.size_or_volume = f"{vol_match.group(1)} {vol_match.group(2)}"

    if not spec.size_or_volume:
        size_match = re.search(r"(\d+(?:\.\d+)?)\s*(mm|cm)", lower)
        if size_match:
            spec.size_or_volume = f"{size_match.group(1)} {size_match.group(2)}"

    dims = _extract_dimensions(message)
    if dims:
        spec.dimensions.update(dims)


def spec_summary(spec: DesignSpec) -> str:
    friendly = {
        "Product Type": spec.product_type or "Not provided",
        "Approx Size/Volume": spec.size_or_volume or "Not provided",
        "Intended Material": spec.intended_material or "Not provided",
        "Closure Type": spec.closure_type or "Not provided",
        "Design Style": spec.design_style or "Not provided",
    }
    if spec.dimensions:
        dim_txt = ", ".join(f"{k}={v} mm" for k, v in spec.dimensions.items())
        friendly["Dimensions"] = dim_txt
    return " | ".join(f"{k}: {v}" for k, v in friendly.items())


def missing_fields(spec: DesignSpec) -> list[str]:
    missing = []
    if not spec.product_type:
        missing.append("product type")
    if not spec.size_or_volume:
        missing.append("approx size or volume")
    if not spec.intended_material:
        missing.append("intended material")
    if not spec.closure_type:
        missing.append("closure type")
    if not spec.design_style:
        missing.append("design style")
    return missing


def required_questions_for_missing(missing: list[str]) -> list[str]:
    mapping = {
        "product type": "What packaging type do you want (jar, bottle, cap, or container)?",
        "approx size or volume": "What is the approximate size or volume (for example 50 ml or 120 mm height)?",
        "intended material": "What material should we target (for example PP, PET, HDPE, or glass)?",
        "closure type": "What closure type do you want (screw, flip top, snap, pump, etc.)?",
        "design style": "What design style should the concept follow (minimal, matte, luxury, etc.)?",
    }
    return [mapping[m] for m in missing if m in mapping]


def _baseline_decision(spec: DesignSpec) -> str:
    if spec.product_type in {"jar", "cosmetic_jar", "bottle"}:
        return "Searching for a similar baseline design…"
    return "No close baseline found. Creating a new concept."


def _is_confirm(message: str) -> bool:
    low = message.lower()
    return any(w in low for w in CONFIRM_WORDS)


def handle_chat_turn(state: SessionState, user_message: str) -> tuple[str, dict[str, Any]]:
    state.history.append({"role": "user", "content": user_message})
    update_spec_from_message(state.spec, user_message)
    state.missing_fields = missing_fields(state.spec)
    state.required_questions = required_questions_for_missing(state.missing_fields)

    assistant_message = ""

    if state.step <= 2:
        if state.missing_fields:
            state.step = 1
            assistant_message = "To continue, I need: " + ", ".join(state.missing_fields) + "."
            if state.required_questions:
                assistant_message += " " + " ".join(state.required_questions[:2])
        else:
            state.step = 3

    if state.step == 3 and not state.baseline_decision_done:
        state.baseline_decision = _baseline_decision(state.spec)
        state.baseline_decision_done = True
        assistant_message = state.baseline_decision

    elif state.step == 3 and state.baseline_decision_done:
        state.step = 4
        assistant_message = (
            "Baseline decision is complete. Use Generate 2D Concept to create the first visual reference."
        )

    elif state.step == 4:
        if not state.images:
            assistant_message = "Please generate the first 2D concept image so we can start visual iteration."
        elif any(w in user_message.lower() for w in ["lock", "final", "ready", "freeze"]):
            state.step = 5
            state.lock_question_asked = True
            assistant_message = "Please approve a version from Version History, then generate the 3D preview."
        else:
            assistant_message = (
                "I captured your iteration request. Use Iterate Design to refine the current 2D reference while preserving design consistency."
            )

    elif state.step == 5:
        if state.approved_image_version:
            state.step = 6
            assistant_message = "Approved version is set. 3D preview generation is enabled."
        elif _is_confirm(user_message):
            assistant_message = "Please click Approve on a version in Edit Studio first."
        else:
            assistant_message = "Understood. Continue iterating or approve a version from Edit Studio when ready."

    elif state.step == 6:
        if state.preview_3d_file:
            state.step = 7
            assistant_message = "Final 3D preview is available in Approve & 3D."
        else:
            assistant_message = "3D preview generation is enabled."

    elif state.step == 7:
        assistant_message = "Final 3D preview is available."

    if assistant_message:
        state.history.append({"role": "assistant", "content": assistant_message})

    flags = {
        "can_generate_image": state.step >= 3 and not state.images,
        "can_iterate_image": state.step >= 4 and bool(state.images) and not state.lock_confirmed,
        "can_lock": state.step == 5 and bool(state.images),
        "can_generate_cad": False,
        "required_questions": state.required_questions,
    }
    return assistant_message, flags
