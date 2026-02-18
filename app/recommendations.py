from __future__ import annotations

from app.models import DesignSpec


def build_edit_recommendations(spec: DesignSpec) -> list[str]:
    recs: list[str] = []
    ptype = (spec.product_type or "").lower()
    material = (spec.intended_material or "").lower()
    style = (spec.design_style or "").lower()
    closure = (spec.closure_type or "").lower()

    if ptype in {"jar", "cosmetic_jar"}:
        recs.append("Increase cap height by 8% for better shelf presence.")
        recs.append("Reduce shoulder radius slightly for a tighter premium profile.")
    if ptype == "bottle":
        recs.append("Narrow neck transition for better ergonomic pour posture.")
        recs.append("Raise shoulder start point by 5% to improve label panel area.")

    if material in {"pp", "hdpe", "pet"}:
        recs.append("Add subtle draft-friendly taper cue to communicate molded feasibility.")
    if material == "glass":
        recs.append("Thicken visual base proportion to imply glass stability.")

    if "matte" in style:
        recs.append("Increase matte softness and reduce specular highlight intensity.")
    if "luxury" in style or "premium" in style:
        recs.append("Introduce controlled metallic accent on closure ring.")
    if "minimal" in style:
        recs.append("Simplify silhouette contrast by removing one secondary groove.")

    if "flip" in closure:
        recs.append("Make flip-top hinge zone visually stronger and slightly wider.")
    if "screw" in closure:
        recs.append("Refine cap knurl band for better grip and consistent rhythm.")

    deduped = []
    seen = set()
    for r in recs:
        if r not in seen:
            deduped.append(r)
            seen.add(r)
    return deduped[:6]
