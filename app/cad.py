from __future__ import annotations

from textwrap import dedent
from typing import TypedDict

from app.models import DesignSpec


class CadGenerationError(Exception):
    pass


class CadGenerationResult(TypedDict):
    cad_code: str
    summary: str


JAR_REQUIRED_DIMENSIONS = ["outer_diameter_mm", "height_mm", "wall_thickness_mm", "cap_height_mm"]
BOTTLE_REQUIRED_DIMENSIONS = [
    "body_diameter_mm",
    "body_height_mm",
    "neck_diameter_mm",
    "neck_height_mm",
    "wall_thickness_mm",
]


def required_dimensions_for_type(product_type: str | None) -> list[str]:
    if product_type in {"jar", "cosmetic_jar"}:
        return JAR_REQUIRED_DIMENSIONS
    if product_type == "bottle":
        return BOTTLE_REQUIRED_DIMENSIONS
    return []


def generate_cadquery_code(spec: DesignSpec) -> CadGenerationResult:
    ptype = (spec.product_type or "").lower()
    dims = spec.dimensions

    required = required_dimensions_for_type(ptype)
    missing = [k for k in required if k not in dims]
    if missing:
        raise CadGenerationError(
            "Missing CAD dimensions: " + ", ".join(missing) + ". Provide these in mm before CAD generation."
        )

    material = (spec.intended_material or "other").lower()
    draft = 1.5 if material in {"pp", "pet", "hdpe", "other"} else 0.0

    if ptype in {"jar", "cosmetic_jar"}:
        od = dims["outer_diameter_mm"]
        h = dims["height_mm"]
        wall = dims["wall_thickness_mm"]
        cap_h = dims["cap_height_mm"]

        summary = (
            f"Cosmetic jar with screw-cap style closure, OD {od} mm, body height {h} mm, "
            f"wall {wall} mm, cap height {cap_h} mm, material {spec.intended_material or 'unspecified'}."
        )

        code = f"""
import cadquery as cq

# Cosmetic jar + simplified screw cap for STEP-ready solid export
outer_diameter = {od}
body_height = {h}
wall = {wall}
cap_height = {cap_h}
draft_deg = {draft}

inner_diameter = outer_diameter - (2 * wall)
if inner_diameter <= 0:
    raise ValueError("wall_thickness_mm is too large for given outer_diameter_mm")

# Jar body with draft for injection molded plastics; draft is 0 for glass.
body = (
    cq.Workplane("XY")
    .circle(outer_diameter / 2)
    .extrude(body_height, taper=-draft_deg)
)

cavity = (
    cq.Workplane("XY")
    .workplane(offset=wall)
    .circle(inner_diameter / 2)
    .extrude(body_height - wall)
)
jar = body.cut(cavity)

# Simplified cap shell (thread omitted intentionally for robust parametric generation)
cap_outer = outer_diameter * 1.02
cap_inner = cap_outer - (2 * wall)
cap = (
    cq.Workplane("XY")
    .workplane(offset=body_height)
    .circle(cap_outer / 2)
    .extrude(cap_height, taper=-draft_deg)
)
cap_void = (
    cq.Workplane("XY")
    .workplane(offset=body_height + wall)
    .circle(cap_inner / 2)
    .extrude(cap_height - wall)
)
cap = cap.cut(cap_void)

assembly = cq.Assembly()
assembly.add(jar, name="jar")
assembly.add(cap, name="cap")

# STEP export compatibility
cq.exporters.export(jar, "jar.step")
cq.exporters.export(cap, "jar_cap.step")
"""
        return {"cad_code": dedent(code).strip(), "summary": summary}

    if ptype == "bottle":
        bd = dims["body_diameter_mm"]
        bh = dims["body_height_mm"]
        nd = dims["neck_diameter_mm"]
        nh = dims["neck_height_mm"]
        wall = dims["wall_thickness_mm"]

        summary = (
            f"Bottle with simplified flip-top cap geometry, body diameter {bd} mm, body height {bh} mm, "
            f"neck diameter {nd} mm, neck height {nh} mm, wall {wall} mm, material {spec.intended_material or 'unspecified'}."
        )

        code = f"""
import cadquery as cq

# Bottle + simplified flip-top cap (hinge as conceptual feature), STEP-ready solids
body_diameter = {bd}
body_height = {bh}
neck_diameter = {nd}
neck_height = {nh}
wall = {wall}
draft_deg = {draft}

inner_body_diameter = body_diameter - (2 * wall)
if inner_body_diameter <= 0:
    raise ValueError("wall_thickness_mm is too large for given body_diameter_mm")

body = (
    cq.Workplane("XY")
    .circle(body_diameter / 2)
    .extrude(body_height, taper=-draft_deg)
)
shoulder = (
    cq.Workplane("XY")
    .workplane(offset=body_height)
    .circle(body_diameter / 2)
    .workplane(offset=neck_height)
    .circle(neck_diameter / 2)
    .loft(combine=True)
)
neck = (
    cq.Workplane("XY")
    .workplane(offset=body_height + neck_height)
    .circle(neck_diameter / 2)
    .extrude(neck_height * 0.4)
)
bottle_outer = body.union(shoulder).union(neck)

cavity = (
    cq.Workplane("XY")
    .workplane(offset=wall)
    .circle(inner_body_diameter / 2)
    .extrude(body_height + neck_height)
)
bottle = bottle_outer.cut(cavity)

# Simplified flip-top cap, thread omitted intentionally for robust manufacturable base geometry
cap_h = neck_height * 0.9
cap_outer = neck_diameter * 1.15
cap_inner = cap_outer - (2 * wall)
cap_base = (
    cq.Workplane("XY")
    .workplane(offset=body_height + neck_height * 1.4)
    .circle(cap_outer / 2)
    .extrude(cap_h)
)
cap_void = (
    cq.Workplane("XY")
    .workplane(offset=body_height + neck_height * 1.4 + wall)
    .circle(cap_inner / 2)
    .extrude(max(cap_h - wall, wall * 0.5))
)
cap = cap_base.cut(cap_void)
lid = (
    cq.Workplane("XY")
    .workplane(offset=body_height + neck_height * 1.4 + cap_h)
    .rect(cap_outer * 0.9, cap_outer * 0.9)
    .extrude(wall)
)
cap = cap.union(lid)

cq.exporters.export(bottle, "bottle.step")
cq.exporters.export(cap, "flip_top_cap.step")
"""
        return {"cad_code": dedent(code).strip(), "summary": summary}

    raise CadGenerationError(
        "Unsupported packaging type for CAD generation. Supported types: cosmetic jar and bottle."
    )
