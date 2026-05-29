"""
Plan generator - LLM-based with rule-based fallback.

V0.4: Integrated LLM structured output for plan generation.
Rule-based generator retained as fallback when LLM is unavailable.
"""

import re
from app.schemas.cad_state import DocumentState
from app.llm.llm_provider import generate_plan_with_llm


def generate_plan(user_input: str, document_state: DocumentState | None = None) -> dict:
    """
    生成建模计划。优先使用 LLM，失败时回退到规则引擎。

    Returns a dict matching the PlanResponse schema.
    """
    # 尝试使用 LLM 生成计划
    llm_result = generate_plan_with_llm(user_input)
    if llm_result is not None:
        return llm_result
    
    # LLM 失败，回退到规则引擎
    return _generate_plan_with_rules(user_input, document_state)


def _generate_plan_with_rules(user_input: str, document_state: DocumentState | None = None) -> dict:
    """
    规则引擎回退方案：使用关键词匹配生成计划。
    """
    text = user_input.lower()

    # Extract dimensions if present
    dims = _extract_dimensions(user_input)

    # Rule: box / baseplate / 底座 / 长方体
    if _matches(text, ["底座", "长方体", "立方体", "盒子", "box", "底板", "baseplate", "block"]):
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
    """Extract dimensions from input."""
    dims: dict[str, float] = {}

    # Pattern 1: "100×60×20" or "100*60*20" or "100x60x20"
    pattern = r"(\d+(?:\.\d+)?)\s*[×x\*]\s*(\d+(?:\.\d+)?)\s*[×x\*]\s*(\d+(?:\.\d+)?)"
    match = re.search(pattern, text)
    if match:
        dims["length"] = float(match.group(1))
        dims["width"] = float(match.group(2))
        dims["height"] = float(match.group(3))
        return dims

    # Pattern 2: "长200宽150高100" (Chinese labeled dimensions)
    lwh = re.search(r"长\s*(\d+(?:\.\d+)?)\s*宽\s*(\d+(?:\.\d+)?)\s*高\s*(\d+(?:\.\d+)?)", text)
    if lwh:
        dims["length"] = float(lwh.group(1))
        dims["width"] = float(lwh.group(2))
        dims["height"] = float(lwh.group(3))
        return dims

    # Pattern 3: "长宽高都是50" (all same value)
    same_val = re.search(r"长\s*宽\s*高\s*都\s*是?\s*(\d+(?:\.\d+)?)", text)
    if same_val:
        v = float(same_val.group(1))
        dims["length"] = v
        dims["width"] = v
        dims["height"] = v
        return dims

    # Pattern 4: individual labeled dims "长100" "宽50" "高30"
    for key, label in [("length", "长"), ("width", "宽"), ("height", "高")]:
        m = re.search(rf"{label}\s*(\d+(?:\.\d+)?)", text)
        if m:
            dims[key] = float(m.group(1))

    # "R25" or "半径25" for radius
    radius_pattern = r"[Rr]\s*(\d+(?:\.\d+)?)"
    match = re.search(radius_pattern, text)
    if match:
        dims["radius"] = float(match.group(1))
    else:
        m = re.search(r"半径\s*(\d+(?:\.\d+)?)", text)
        if m:
            dims["radius"] = float(m.group(1))

    # "高度50" for height (only if not already extracted)
    if "height" not in dims:
        m = re.search(r"高度\s*(\d+(?:\.\d+)?)", text)
        if m:
            dims["height"] = float(m.group(1))

    return dims
