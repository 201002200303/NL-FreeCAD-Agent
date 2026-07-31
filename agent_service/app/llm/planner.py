"""
Plan generator - LLM-based with rule-based fallback.

V0.4: Integrated LLM structured output for plan generation.
V0.7: Added high-level plan generation for closed-loop architecture.
Rule-based generator retained as fallback when LLM is unavailable.
"""

import re
from app.schemas.cad_state import DocumentState
from app.llm.llm_provider import (
    generate_plan_with_llm,
    generate_high_level_plan_with_llm,
    generate_next_tool_calls_with_llm,
    evaluate_step_with_llm,
)


def generate_plan(user_input: str, document_state: DocumentState | None = None) -> dict:
    """
    生成建模计划。优先使用 LLM，失败时回退到规则引擎。

    Returns a dict matching the PlanResponse schema.
    """
    llm_result = generate_plan_with_llm(user_input, document_state)
    if llm_result is not None:
        return llm_result

    return _generate_plan_with_rules(user_input, document_state)


def generate_high_level_plan(
    user_input: str, document_state: DocumentState | None = None
) -> dict:
    """
    生成高层建模计划（phase-level，不绑定具体工具参数）。

    V0.7: 用于闭环架构的 start_plan 端点。
    """
    llm_result = generate_high_level_plan_with_llm(user_input, document_state)
    if llm_result is not None:
        return llm_result

    return _generate_high_level_plan_with_rules(user_input, document_state)


def generate_next_tool_calls(
    session_id: str,
    user_input: str,
    high_level_plan: dict,
    current_phase_id: str,
    document_state: DocumentState,
    execution_history: dict,
    name_map: dict[str, str],
    session_memory: dict | None = None,
) -> dict:
    """
    生成下一步工具调用。

    V0.7: 用于闭环架构的 next_step 端点。
    """
    return generate_next_tool_calls_with_llm(
        session_id=session_id,
        user_input=user_input,
        high_level_plan=high_level_plan,
        current_phase_id=current_phase_id,
        document_state=document_state,
        execution_history=execution_history,
        name_map=name_map,
        session_memory=session_memory,
    )


def evaluate_step_result(
    session_id: str,
    last_tool_call: dict,
    execution_result: dict,
    document_state: DocumentState,
    execution_history: dict,
    high_level_plan: dict | None = None,
    current_phase_id: str | None = None,
    *,
    deterministic_checks: dict | None = None,
    validator_results: list[dict] | None = None,
    current_abstract_step: dict | None = None,
    session_memory: dict | None = None,
) -> dict:
    """
    评估步骤执行结果，决定下一步动作。

    V0.7: 用于闭环架构的 evaluate_step 端点。
    """
    return evaluate_step_with_llm(
        session_id=session_id,
        last_tool_call=last_tool_call,
        execution_result=execution_result,
        document_state=document_state,
        execution_history=execution_history,
        high_level_plan=high_level_plan,
        current_phase_id=current_phase_id,
        deterministic_checks=deterministic_checks,
        validator_results=validator_results,
        current_abstract_step=current_abstract_step,
        session_memory=session_memory,
    )


def _generate_high_level_plan_with_rules(
    user_input: str, document_state: DocumentState | None = None
) -> dict:
    """
    规则引擎回退方案：生成简单的高层计划。
    """
    text = user_input.lower()

    # 简单任务：单阶段
    if _matches(text, ["底座", "长方体", "立方体", "盒子", "box", "圆柱", "cylinder"]):
        return {
            "status": "ok",
            "user_input": user_input,
            "goal": user_input,
            "phases": [
                {
                    "phase_id": "P1",
                    "title": "基础几何",
                    "intent": user_input,
                    "success_criteria": [],
                }
            ],
            "assumptions": ["单位默认为 mm"],
        }

    # 复杂任务：多阶段（简单启发式）
    if _matches(text, ["台灯", "椅子", "桌子", "模型"]):
        return {
            "status": "ok",
            "user_input": user_input,
            "goal": user_input,
            "phases": [
                {
                    "phase_id": "P1",
                    "title": "底座",
                    "intent": "创建底座",
                    "success_criteria": [],
                },
                {
                    "phase_id": "P2",
                    "title": "主体",
                    "intent": "创建主体结构",
                    "success_criteria": [],
                },
            ],
            "assumptions": ["单位默认为 mm"],
        }

    # 无法理解
    return {
        "status": "need_more_info",
        "user_input": user_input,
        "goal": "无法确定建模目标",
        "phases": [],
        "assumptions": [],
        "question": "请描述您想创建的模型。",
    }


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
