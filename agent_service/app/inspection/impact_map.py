from pydantic import BaseModel, Field

from app.cad_spec.schemas import CADSpec
from app.schemas.cad_state import DocumentState


HIGH_RISK_FEATURES = {"hole", "fillet", "chamfer", "boolean_cut", "delete", "hide", "transform"}
PRIMITIVE_FEATURES = {"box", "cylinder", "cone", "sphere", "torus"}
DEFERRED_TARGET_FEATURES = {"fillet", "chamfer", "hole"}


class ImpactMap(BaseModel):
    target_objects: list[str] = Field(default_factory=list)
    affected_geometry: list[str] = Field(default_factory=list)
    helper_objects: list[str] = Field(default_factory=list)
    expected_changes: list[str] = Field(default_factory=list)
    risk_points: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    blocked: bool = False
    block_reason: str | None = None


def build_impact_map(cad_spec: CADSpec, document_state: DocumentState | None) -> ImpactMap:
    objects = document_state.objects if document_state else []
    visible_solids = [
        obj.name
        for obj in objects
        if getattr(obj, "visible", True) and getattr(obj, "topology", None) is not None
    ]
    selected = document_state.selected_objects if document_state else []
    primary_target = selected[0] if selected else (visible_solids[0] if visible_solids else None)

    impact = ImpactMap()
    has_create_features = any(feature.type in PRIMITIVE_FEATURES for feature in cad_spec.features)

    for feature in cad_spec.features:
        ftype = feature.type
        if ftype in PRIMITIVE_FEATURES:
            name = feature.name_hint or ftype.title()
            impact.expected_changes.append(f"Create new {ftype} object '{name}'.")
            impact.affected_geometry.append(f"new:{name}")
            continue

        target = feature.target_hint
        if target in (None, "selected_or_primary_solid"):
            target = primary_target

        if target:
            clean_target = _sanitize_target_hint(target)
            if clean_target and clean_target not in impact.target_objects:
                impact.target_objects.append(clean_target)
            impact.affected_geometry.append(f"{ftype}:{clean_target or target}")
            impact.expected_changes.append(f"Apply {ftype} to '{clean_target or target}'.")
        else:
            if has_create_features and ftype in DEFERRED_TARGET_FEATURES:
                impact.requires_confirmation = True
                impact.risk_points.append(
                    f"{ftype} will target the primary solid created in an earlier harness step."
                )
                impact.expected_changes.append(f"Apply {ftype} after primary solid exists.")
                continue
            impact.blocked = True
            impact.block_reason = (
                f"Feature '{ftype}' requires a target object, but no selected or visible solid was found."
            )

        if ftype in HIGH_RISK_FEATURES:
            impact.requires_confirmation = True
            impact.risk_points.append(f"{ftype} modifies existing geometry and should be confirmed.")

        if ftype == "hole":
            impact.helper_objects.append("temporary cutting cylinder")

    return impact


def _sanitize_target_hint(raw: str | None) -> str | None:
    if not raw or raw == "selected_or_primary_solid":
        return None
    text = raw.strip()
    if "," in text:
        parts = [part.strip() for part in text.split(",") if part.strip()]
        return parts[-1] if parts else None
    return text

