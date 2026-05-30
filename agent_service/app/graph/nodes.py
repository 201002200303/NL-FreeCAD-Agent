"""
LangGraph node functions for the CAD Agent workflow.

V0.1-V0.6 nodes:
  parse_input_node  — validate input, prepare document state summary
  plan_node         — generate plan via LLM (with retry context)
  validate_plan_node— structural validation against TOOL_SPECS

V0.7 nodes (closed-loop architecture):
  generate_high_level_plan_node — generate phase-level plan
  validate_high_level_plan_node — validate high-level plan structure
  plan_next_step_node           — generate next tool calls
  validate_next_step_node       — validate next step tool calls
  evaluate_step_node            — evaluate execution result + deterministic checks
"""

from app.graph.state import AgentState
from app.llm.planner import (
    generate_plan,
    generate_high_level_plan,
    generate_next_tool_calls,
    evaluate_step_result,
)
from app.tools.tool_specs import TOOL_SPECS


def _sanitize_tool_calls(calls: list | None, prefix: str = "repair") -> list[dict]:
    """Ensure tool calls satisfy ToolCall schema (call_id required)."""
    sanitized = []
    for i, call in enumerate(calls or []):
        if not isinstance(call, dict) or not call.get("tool"):
            continue
        sanitized.append({
            "call_id": call.get("call_id") or f"{prefix}_{i + 1}",
            "tool": call["tool"],
            "args": call.get("args") or {},
            "description": call.get("description") or "",
            "expected_effect": call.get("expected_effect"),
        })
    return sanitized


def parse_input_node(state: AgentState) -> dict:
    """Parse and normalize user input, initialize retry state."""
    user_input = state.get("user_input", "").strip()

    updates: dict = {
        "retry_count": 0,
        "validation_errors": [],
    }

    if not user_input:
        updates["status"] = "error"
        updates["error_message"] = "用户输入为空"
    else:
        updates["status"] = "parsed"
        updates["error_message"] = None

    return updates


def plan_node(state: AgentState) -> dict:
    """Generate a modeling plan. On retry, include previous errors for self-correction."""
    retry_count = state.get("retry_count", 0)
    validation_errors = state.get("validation_errors", [])

    # On retry, append error context to user input so LLM can self-correct
    user_input = state["user_input"]
    if retry_count > 0 and validation_errors:
        error_context = "\n\n[系统反馈] 上一次生成的计划存在以下问题，请修正后重新生成：\n"
        for err in validation_errors:
            error_context += f"- {err}\n"
        user_input = state["user_input"] + error_context

    result = generate_plan(user_input, state.get("document_state"))

    return {
        "plan_json": result,
        "status": "planned",
    }


def validate_plan_node(state: AgentState) -> dict:
    """Validate the generated plan against tool specs."""
    plan_json = state.get("plan_json")

    if not plan_json:
        return {
            "status": "error",
            "error_message": "未能生成计划",
            "validation_errors": ["plan_json 为空"],
        }

    # If LLM already said need_more_info, skip structural validation
    if plan_json.get("status") == "need_more_info":
        return {
            "status": "need_more_info",
            "validation_errors": [],
        }

    errors = _validate_plan(plan_json)

    if errors:
        return {
            "status": "validation_failed",
            "validation_errors": errors,
            "error_message": "; ".join(errors),
        }

    return {
        "status": "ok",
        "validation_errors": [],
    }


# ── Validation helpers ──────────────────────────────────────────────

def _validate_plan(plan_json: dict) -> list[str]:
    """Validate plan structure and tool calls against TOOL_SPECS."""
    errors: list[str] = []
    steps = plan_json.get("plan", [])

    if not isinstance(steps, list):
        return ["plan 字段必须是列表"]

    step_ids: set[str] = set()

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"步骤 {i + 1}: 必须是字典")
            continue

        step_id = step.get("step_id", f"step_{i + 1}")
        tool = step.get("tool", "")
        args = step.get("args", {})

        # Duplicate step_id
        if step_id in step_ids:
            errors.append(f"步骤 {step_id}: 重复的 step_id")
        step_ids.add(step_id)

        # Tool name validation
        if not tool:
            errors.append(f"步骤 {step_id}: 缺少 tool 字段")
            continue

        if tool not in TOOL_SPECS:
            valid = ", ".join(TOOL_SPECS.keys())
            errors.append(f"步骤 {step_id}: 未知工具 '{tool}'，可用工具: {valid}")
            continue

        spec = TOOL_SPECS[tool]

        # Required params
        for req in spec.get("required", []):
            if req not in args:
                errors.append(f"步骤 {step_id}: 工具 '{tool}' 缺少必填参数 '{req}'")

        # Basic type check for provided params
        params_spec = spec.get("parameters", {})
        for arg_name, arg_value in args.items():
            if arg_name in params_spec:
                expected_type = params_spec[arg_name].get("type", "")
                if not _check_type(arg_value, expected_type):
                    errors.append(
                        f"步骤 {step_id}: 参数 '{arg_name}' 期望类型 {expected_type}，"
                        f"实际为 {type(arg_value).__name__}"
                    )

        # Dependency validation
        depends_on = step.get("depends_on", [])
        if isinstance(depends_on, list):
            for dep in depends_on:
                if dep not in step_ids:
                    errors.append(f"步骤 {step_id}: 依赖 '{dep}' 未定义或顺序错误")

    return errors


_TYPE_MAP = {
    "float": (int, float),
    "int": (int,),
    "string": (str,),
    "bool": (bool,),
    "list": (list,),
    "dict": (dict,),
}


def _check_type(value, expected_type: str) -> bool:
    """Check if value matches the expected type string."""
    types = _TYPE_MAP.get(expected_type)
    if types is None:
        return True
    # bool is subclass of int in Python, so exclude it for numeric checks
    if expected_type in ("float", "int") and isinstance(value, bool):
        return False
    return isinstance(value, types)


def should_end(state: AgentState) -> str:
    """Routing function for conditional edge after validate_plan."""
    status = state.get("status", "")
    retry_count = state.get("retry_count", 0)
    max_retries = 2

    if status == "ok" or status == "need_more_info":
        return "end"
    if retry_count >= max_retries:
        return "end"
    return "retry"


# ── V0.7: High-level plan nodes ────────────────────────────────────


def generate_high_level_plan_node(state: AgentState) -> dict:
    """Generate a high-level phase plan via LLM."""
    user_input = state["user_input"]
    document_state = state.get("document_state")

    result = generate_high_level_plan(user_input, document_state)

    if result.get("status") == "error":
        return {
            "high_level_plan": None,
            "status": "error",
            "error_message": result.get("message", "生成高层计划失败"),
        }

    return {
        "high_level_plan": result,
        "phases": result.get("phases", []),
        "status": "high_level_planned",
    }


def validate_high_level_plan_node(state: AgentState) -> dict:
    """Validate the high-level plan structure."""
    high_level_plan = state.get("high_level_plan")

    if not high_level_plan:
        return {
            "status": "error",
            "error_message": "高层计划为空",
        }

    if high_level_plan.get("status") == "need_more_info":
        return {"status": "need_more_info"}

    phases = high_level_plan.get("phases", [])
    if not phases:
        return {
            "status": "error",
            "error_message": "高层计划中没有阶段",
        }

    errors = []
    phase_ids = set()
    for phase in phases:
        phase_id = phase.get("phase_id")
        if not phase_id:
            errors.append("阶段缺少 phase_id")
        elif phase_id in phase_ids:
            errors.append(f"重复的 phase_id: {phase_id}")
        else:
            phase_ids.add(phase_id)

        if not phase.get("intent"):
            errors.append(f"阶段 {phase_id} 缺少 intent")

    if errors:
        return {
            "status": "validation_failed",
            "error_message": "; ".join(errors),
        }

    return {"status": "ok"}


# ── V0.7: Next step nodes ──────────────────────────────────────────


def plan_next_step_node(state: AgentState) -> dict:
    """Generate next tool calls based on current state and history."""
    session_id = state.get("session_id", "default")
    user_input = state["user_input"]
    high_level_plan = state.get("high_level_plan", {})
    current_phase_id = state.get("current_phase_id")
    document_state = state.get("document_state")
    execution_history = state.get("execution_history", {})
    name_map = state.get("name_map", {})

    if not current_phase_id:
        phases = high_level_plan.get("phases", [])
        if phases:
            current_phase_id = phases[0]["phase_id"]
        else:
            return {
                "next_step_result": {
                    "decision": "finish",
                    "message": "没有可执行的阶段",
                },
                "status": "finished",
            }

    result = generate_next_tool_calls(
        session_id=session_id,
        user_input=user_input,
        high_level_plan=high_level_plan,
        current_phase_id=current_phase_id,
        document_state=document_state,
        execution_history=execution_history,
        name_map=name_map,
    )

    return {
        "next_step_result": result,
        "current_phase_id": current_phase_id,
        "status": "next_step_planned",
    }


def validate_next_step_node(state: AgentState) -> dict:
    """Validate the next step tool calls."""
    next_step_result = state.get("next_step_result", {})

    decision = next_step_result.get("decision", "")
    if decision in ("finish", "abort", "ask_user"):
        return {"status": "ok"}

    tool_calls = next_step_result.get("tool_calls", [])
    if not tool_calls:
        return {
            "status": "ok",
        }

    errors = []
    for i, call in enumerate(tool_calls):
        if not call.get("tool"):
            errors.append(f"tool_call {i}: 缺少 tool 字段")
            continue

        tool_name = call["tool"]
        if tool_name not in TOOL_SPECS:
            valid = ", ".join(TOOL_SPECS.keys())
            errors.append(f"tool_call {i}: 未知工具 '{tool_name}'，可用: {valid}")
            continue

        spec = TOOL_SPECS[tool_name]
        args = call.get("args", {})
        for req in spec.get("required", []):
            if req not in args:
                errors.append(f"tool_call {i}: '{tool_name}' 缺少必填参数 '{req}'")

    if errors:
        return {
            "status": "validation_failed",
            "error_message": "; ".join(errors),
        }

    return {"status": "ok"}


# ── V0.7: Evaluate step node ───────────────────────────────────────


def evaluate_step_node(state: AgentState) -> dict:
    """Evaluate execution result and determine next action."""
    from app.evaluation.rules import run_deterministic_checks
    from app.evaluation.phases import normalize_evaluate_decision

    session_id = state.get("session_id", "default")
    last_tool_call = state.get("last_tool_call", {})
    execution_result = state.get("execution_result", {})
    document_state = state.get("document_state")
    execution_history = state.get("execution_history", {})
    high_level_plan = state.get("high_level_plan")
    current_phase_id = state.get("current_phase_id")

    det_result = run_deterministic_checks(
        last_tool_call=last_tool_call,
        execution_result=execution_result,
        document_state=document_state,
    )

    if not det_result["passed"]:
        suggested = det_result.get("suggested_decision", "repair")
        recent = execution_history.get("recent", [])
        fail_count = sum(1 for e in recent[-3:] if e.get("status") == "error")

        if fail_count >= 2 and suggested == "repair":
            result = {
                "decision": "skip_and_continue",
                "phase_status": "in_progress",
                "message": f"连续失败，跳过: {'; '.join(det_result['issues'])}",
                "deterministic_issues": det_result["issues"],
            }
        else:
            result = {
                "decision": suggested,
                "phase_status": "in_progress",
                "message": "; ".join(det_result["issues"]),
                "deterministic_issues": det_result["issues"],
            }
            if suggested == "repair":
                llm_result = evaluate_step_result(
                    session_id=session_id,
                    last_tool_call=last_tool_call,
                    execution_result=execution_result,
                    document_state=document_state,
                    execution_history=execution_history,
                    high_level_plan=high_level_plan,
                    current_phase_id=current_phase_id,
                )
                result["repair_tool_calls"] = _sanitize_tool_calls(
                    llm_result.get("repair_tool_calls", [])
                )
                if llm_result.get("message"):
                    result["message"] = llm_result["message"]
    else:
        result = evaluate_step_result(
            session_id=session_id,
            last_tool_call=last_tool_call,
            execution_result=execution_result,
            document_state=document_state,
            execution_history=execution_history,
            high_level_plan=high_level_plan,
            current_phase_id=current_phase_id,
        )
        result.setdefault("deterministic_issues", [])

    result = normalize_evaluate_decision(result, high_level_plan, current_phase_id)

    new_phase_id = result.get("updated_current_phase_id")
    updates = {
        "evaluate_result": result,
        "status": "evaluated",
    }
    if new_phase_id:
        updates["current_phase_id"] = new_phase_id

    return updates
