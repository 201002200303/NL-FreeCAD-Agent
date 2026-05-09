"""
Rule-based plan generator (stub).

In V0.1, this uses simple keyword matching to generate a modeling plan.
It will be replaced by LangGraph + LLM structured output in V0.4+.
"""

import re
from app.schemas.cad_state import DocumentState


def generate_plan(user_input: str, document_state: DocumentState | None = None) -> dict:
    """
    Stub plan generator using keyword rules.

    Returns a dict matching the PlanResponse schema.
    """
    text = user_input.lower()

    # Extract dimensions if present
    dims = _extract_dimensions(user_input)

    # Rule: box / baseplate / 底座 / 长方体
    if _matches(text, ["底座", "长方体", "盒子", "box", "底板", "baseplate", "block"]):
        length = dims.get("length", 100)
        width = dims.get("width", 60)
        height = dims.get("height", 20)
        name = _pick_name(text, "BaseBlock")
        return {
            "status": "ok",
            "goal": f"创建一个 {length}×{width}×{height}mm 的长方体",
            "assumptions": ["单位默认为 mm"],
            "missing_params": [],
            "question": None,
            "plan": [
                {
                    "step_id": "S1",
                    "description": f"创建 {length}×{width}×{height}mm 长方体",
                    "tool": "create_box",
                    "args": {
                        "name": name,
                        "length": length,
                        "width": width,
                        "height": height,
                        "unit": "mm",
                    },
                    "depends_on": [],
                    "expected_result": {"object": name, "type": "Part::Box"},
                }
            ],
        }

    # Rule: cylinder / 圆柱
    if _matches(text, ["圆柱", "cylinder", "柱体"]):
        radius = dims.get("radius", 25)
        height = dims.get("height", 50)
        name = _pick_name(text, "Cylinder")
        return {
            "status": "ok",
            "goal": f"创建一个 R{radius}×H{height}mm 的圆柱体",
            "assumptions": ["单位默认为 mm"],
            "missing_params": [],
            "question": None,
            "plan": [
                {
                    "step_id": "S1",
                    "description": f"创建 R{radius}×H{height}mm 圆柱体",
                    "tool": "create_cylinder",
                    "args": {
                        "name": name,
                        "radius": radius,
                        "height": height,
                        "unit": "mm",
                    },
                    "depends_on": [],
                    "expected_result": {"object": name, "type": "Part::Cylinder"},
                }
            ],
        }

    # Rule: sketch / 草图
    if _matches(text, ["草图", "sketch"]):
        name = _pick_name(text, "Sketch")
        return {
            "status": "ok",
            "goal": "创建草图",
            "assumptions": ["草图平面默认为 XY"],
            "missing_params": [],
            "question": None,
            "plan": [
                {
                    "step_id": "S1",
                    "description": "创建草图",
                    "tool": "create_sketch",
                    "args": {"name": name, "plane": "XY"},
                    "depends_on": [],
                    "expected_result": {"object": name, "type": "Sketcher::SketchObject"},
                }
            ],
        }

    # Fallback: cannot understand
    return {
        "status": "need_more_info",
        "goal": "无法确定建模目标",
        "assumptions": [],
        "missing_params": [],
        "question": "请描述您想创建的模型。当前支持：长方体（底座）、圆柱体、草图。示例：\"创建一个 100×60×20mm 的底座\"",
        "plan": [],
    }


def _matches(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


def _pick_name(text: str, default: str) -> str:
    """Try to extract an English name from input, fallback to default."""
    return default


def _extract_dimensions(text: str) -> dict[str, float]:
    """Extract dimensions like 100×60×20 from input."""
    dims: dict[str, float] = {}
    # Match patterns like "100×60×20" or "100*60*20" or "100x60x20"
    pattern = r"(\d+(?:\.\d+)?)\s*[×x\*]\s*(\d+(?:\.\d+)?)\s*[×x\*]\s*(\d+(?:\.\d+)?)"
    match = re.search(pattern, text)
    if match:
        dims["length"] = float(match.group(1))
        dims["width"] = float(match.group(2))
        dims["height"] = float(match.group(3))
        return dims
    # Match "R25" or "半径25" for radius
    radius_pattern = r"[Rr]\s*(\d+(?:\.\d+)?)"
    match = re.search(radius_pattern, text)
    if match:
        dims["radius"] = float(match.group(1))
    return dims
