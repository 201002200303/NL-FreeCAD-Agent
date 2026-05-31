import re

from app.cad_spec.schemas import CADFeature, CADSpec, SpecGenerationResult


def generate_cad_spec(user_input: str) -> SpecGenerationResult:
    """Convert natural language into a tool-free CAD specification.

    Priority: LLM structured spec → rule-based fallback.
    """
    text = (user_input or "").strip()
    if not text:
        return SpecGenerationResult(
            status="need_more_info",
            user_input=user_input,
            question="Please describe the model you want to create.",
        )

    from app.llm.llm_provider import generate_cad_spec_with_llm

    llm_result = generate_cad_spec_with_llm(user_input)
    if llm_result is not None:
        return llm_result

    return _generate_cad_spec_with_rules(user_input)


def _generate_cad_spec_with_rules(user_input: str) -> SpecGenerationResult:
    """Rule-based fallback when LLM is unavailable."""
    text = (user_input or "").strip()
    lowered = text.lower()
    if not text:
        return SpecGenerationResult(
            status="need_more_info",
            user_input=user_input,
            question="Please describe the model you want to create.",
        )

    dimensions = _extract_dimensions(text)
    features: list[CADFeature] = []
    assumptions = ["Unit defaults to mm when not specified."]
    unknowns: list[str] = []

    model_type = "generic"

    if _has_any(lowered, ["box", "block", "base", "plate", "底座", "底板", "长方体", "方块"]):
        model_type = "box" if model_type == "generic" else model_type
        dims = {
            "length": dimensions.get("length", 100.0),
            "width": dimensions.get("width", 60.0),
            "height": dimensions.get("height", 20.0),
        }
        _record_defaulted_dimensions(dimensions, dims, assumptions)
        features.append(CADFeature(type="box", name_hint="Base", dimensions=dims))

    if _has_any(lowered, ["cylinder", "柱", "圆柱", "shaft", "轴"]):
        model_type = "cylinder" if model_type == "generic" else model_type
        dims = {
            "radius": dimensions.get("radius", 25.0),
            "height": dimensions.get("height", 50.0),
        }
        _record_defaulted_dimensions(dimensions, dims, assumptions)
        features.append(CADFeature(type="cylinder", name_hint="Cylinder", dimensions=dims))

    if _has_any(lowered, ["lamp", "台灯"]):
        model_type = "lamp"
        if not features:
            features.extend(
                [
                    CADFeature(type="cylinder", name_hint="Base", dimensions={"radius": 45.0, "height": 8.0}),
                    CADFeature(type="cylinder", name_hint="Stem", dimensions={"radius": 5.0, "height": 80.0}, position="on_base_center"),
                    CADFeature(type="cone", name_hint="Shade", dimensions={"radius1": 35.0, "radius2": 18.0, "height": 28.0}, position="on_stem_top"),
                ]
            )
            assumptions.append("Lamp defaults to a cylinder base, vertical stem, and conical shade.")

    if _has_any(lowered, ["hole", "孔", "开孔"]):
        features.append(
            CADFeature(
                type="hole",
                name_hint="Hole",
                dimensions={"radius": dimensions.get("hole_radius", dimensions.get("radius", 5.0))},
                position="center",
                target_hint="selected_or_primary_solid",
            )
        )

    if _has_any(lowered, ["fillet", "round", "倒圆", "圆角"]):
        features.append(
            CADFeature(
                type="fillet",
                dimensions={"radius": dimensions.get("fillet_radius", dimensions.get("radius", 2.0))},
                target_hint="selected_or_primary_solid",
            )
        )

    if _has_any(lowered, ["chamfer", "倒角"]):
        features.append(
            CADFeature(
                type="chamfer",
                dimensions={"distance": dimensions.get("distance", 2.0)},
                target_hint="selected_or_primary_solid",
            )
        )

    if not features:
        unknowns.append("model_type")
        return SpecGenerationResult(
            status="need_more_info",
            user_input=user_input,
            cad_spec=CADSpec(model_type=model_type, features=[], unknowns=unknowns, assumptions=assumptions),
            question="I could not identify a supported CAD pattern. Please mention a box, cylinder, lamp, hole, fillet, or chamfer.",
        )

    return SpecGenerationResult(
        status="ok",
        user_input=user_input,
        cad_spec=CADSpec(
            model_type=model_type,
            unit="mm",
            coordinate_system="XYZ",
            features=features,
            dimensions=dimensions,
            unknowns=unknowns,
            assumptions=assumptions,
        ),
    )


def _has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _record_defaulted_dimensions(provided: dict[str, float], resolved: dict[str, float], assumptions: list[str]) -> None:
    for key, value in resolved.items():
        if key not in provided:
            assumptions.append(f"{key} defaults to {value:g} mm.")


def _extract_dimensions(text: str) -> dict[str, float]:
    dims: dict[str, float] = {}

    match = re.search(r"(\d+(?:\.\d+)?)\s*[xX\*]\s*(\d+(?:\.\d+)?)\s*[xX\*]\s*(\d+(?:\.\d+)?)", text)
    if match:
        dims["length"] = float(match.group(1))
        dims["width"] = float(match.group(2))
        dims["height"] = float(match.group(3))

    labeled = {
        "length": [r"length\s*(\d+(?:\.\d+)?)", r"长\s*(\d+(?:\.\d+)?)"],
        "width": [r"width\s*(\d+(?:\.\d+)?)", r"宽\s*(\d+(?:\.\d+)?)"],
        "height": [r"height\s*(\d+(?:\.\d+)?)", r"高\s*(\d+(?:\.\d+)?)"],
        "radius": [r"radius\s*(\d+(?:\.\d+)?)", r"[Rr]\s*(\d+(?:\.\d+)?)", r"半径\s*(\d+(?:\.\d+)?)"],
        "distance": [r"distance\s*(\d+(?:\.\d+)?)", r"距离\s*(\d+(?:\.\d+)?)"],
    }
    for key, patterns in labeled.items():
        if key in dims:
            continue
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                dims[key] = float(m.group(1))
                break

    hole = re.search(r"(?:hole|孔).*?(?:radius|半径|R)?\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if hole:
        dims["hole_radius"] = float(hole.group(1))

    fillet = re.search(r"(?:fillet|圆角|倒圆).*?(?:radius|半径|R)?\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if fillet:
        dims["fillet_radius"] = float(fillet.group(1))

    return dims

