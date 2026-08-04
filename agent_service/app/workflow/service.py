"""The whole closed-loop workflow, as plain Python (no LangGraph).

Read top-down:
  start_plan   → build phases + abstract step queue (queue built ONCE)
  next_step    → LLM tool calls → validate specs → maybe prepend queries
  evaluate_step→ deterministic checks → validators → LLM → advance queue
                 → normalize decision (ONLY here)

Legacy V0.1 plan retry lives in `legacy_plan()` (was build_cad_graph).
"""
from __future__ import annotations

from app.abstract_steps.planner import (
    build_queue_from_high_level_plan,
    resolve_current_abstract_step,
    is_queue_exhausted,
)
from app.evaluation.harness import (
    apply_abstract_step_advancement,
    should_advance_abstract_step,
    resolve_validator_names,
)
from app.evaluation.phases import normalize_evaluate_decision
from app.llm.planner import (
    generate_plan,
    generate_high_level_plan,
    generate_next_tool_calls,
    evaluate_step_result,
)
from app.tools.query_policy import (
    build_required_query_calls,
    is_query_tool,
    validate_query_before_act,
)
from app.tools.tool_specs import TOOL_SPECS


# ── shared helpers (moved from graph/nodes.py) ─────────────────────

def sanitize_tool_calls(calls: list | None, prefix: str = "repair") -> list[dict]:
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


_TYPE_MAP = {
    "float": (int, float),
    "int": (int,),
    "string": (str,),
    "bool": (bool,),
    "list": (list,),
    "dict": (dict,),
}


def _check_type(value, expected_type: str) -> bool:
    types = _TYPE_MAP.get(expected_type)
    if types is None:
        return True
    if expected_type in ("float", "int") and isinstance(value, bool):
        return False
    return isinstance(value, types)


def _validate_plan(plan_json: dict) -> list[str]:
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
        if step_id in step_ids:
            errors.append(f"步骤 {step_id}: 重复的 step_id")
        step_ids.add(step_id)
        if not tool:
            errors.append(f"步骤 {step_id}: 缺少 tool 字段")
            continue
        if tool not in TOOL_SPECS:
            valid = ", ".join(TOOL_SPECS.keys())
            errors.append(f"步骤 {step_id}: 未知工具 '{tool}'，可用工具: {valid}")
            continue
        spec = TOOL_SPECS[tool]
        for req in spec.get("required", []):
            if req not in args:
                errors.append(f"步骤 {step_id}: 工具 '{tool}' 缺少必填参数 '{req}'")
        params_spec = spec.get("parameters", {})
        for arg_name, arg_value in args.items():
            if arg_name in params_spec:
                expected_type = params_spec[arg_name].get("type", "")
                if not _check_type(arg_value, expected_type):
                    errors.append(
                        f"步骤 {step_id}: 参数 '{arg_name}' 期望类型 {expected_type}，"
                        f"实际为 {type(arg_value).__name__}"
                    )
        depends_on = step.get("depends_on", [])
        if isinstance(depends_on, list):
            for dep in depends_on:
                if dep not in step_ids:
                    errors.append(f"步骤 {step_id}: 依赖 '{dep}' 未定义或顺序错误")
    return errors


def _validator_is_blocking(result: dict) -> bool:
    """Kept as a re-export: `app.evaluation.validators` owns the policy."""
    from app.evaluation.validators import is_blocking_validator

    return is_blocking_validator(result)


def _consecutive_recent_errors(execution_history: dict | None) -> int:
    if not execution_history:
        return 0
    count = 0
    for entry in reversed(execution_history.get("recent", [])):
        if entry.get("status") == "error":
            count += 1
        else:
            break
    return count


def _skip_default_object_validators(tool_call: dict, execution_result: dict) -> bool:
    tool = tool_call.get("tool", "")
    effect_type = (tool_call.get("expected_effect") or {}).get("type")
    return (
        execution_result.get("kind") == "query"
        or is_query_tool(tool)
        or tool in {"delete_object", "save_fcstd", "export_step", "export_stl"}
        or effect_type in {"deletion", "query", "export"}
    )


# ── 1. start ───────────────────────────────────────────────────────

def start_plan(*, user_input: str, document_state=None) -> dict:
    """Generate high-level plan and initialize the abstract step queue.

    Queue is built exactly once here (previously also inside the plan node).
    """
    result = generate_high_level_plan(user_input, document_state)
    if result.get("status") == "error":
        return {"status": "error", "error_message": result.get("message", "生成高层计划失败")}
    if result.get("status") == "need_more_info":
        return {"status": "need_more_info", "high_level_plan": result}

    high_level_plan = result
    # evaluate 侧 brief 从这里回取；LLM 返回里通常没有该字段
    high_level_plan["user_input"] = user_input
    queue = build_queue_from_high_level_plan(high_level_plan).model_dump(mode="json")
    high_level_plan["abstract_step_queue"] = queue
    high_level_plan.setdefault("recipe_id", queue.get("recipe_id", "llm_session"))
    current_step = resolve_current_abstract_step(queue)
    if current_step and current_step.get("step_id"):
        high_level_plan["current_phase_id"] = current_step["step_id"]
    return {
        "status": "ok",
        "high_level_plan": high_level_plan,
        "abstract_step_queue": queue,
        "current_abstract_step": current_step,
    }


# ── 2. next ────────────────────────────────────────────────────────

def next_step(
    *,
    user_input: str,
    high_level_plan: dict | None,
    current_phase_id: str | None,
    document_state=None,
    execution_history: dict | None = None,
    session_memory: dict | None = None,
    name_map: dict | None = None,
    abstract_step_queue: dict | None = None,
    current_abstract_step: dict | None = None,
    session_id: str = "default",
) -> dict:
    """Plan the next batch of tool calls and validate them."""
    state = {
        "session_id": session_id,
        "user_input": user_input,
        "high_level_plan": high_level_plan or {},
        "current_phase_id": current_phase_id,
        "document_state": document_state,
        "execution_history": execution_history or {},
        "session_memory": session_memory,
        "name_map": name_map or {},
        "abstract_step_queue": abstract_step_queue,
        "current_abstract_step": current_abstract_step,
    }
    planned = plan_next_step_node(state)
    if planned.get("status") == "finished":
        return planned
    validated = validate_next_step_node({**state, **planned})
    return {**planned, **validated}


# ── 3. evaluate ────────────────────────────────────────────────────

def evaluate_step(**kwargs) -> dict:
    return evaluate_step_node(kwargs)


# ── legacy V0.1 plan graph (was build_cad_graph) ──────────────────

def should_end(state: dict) -> str:
    status = state.get("status", "")
    retry_count = state.get("retry_count", 0)
    if status in {"ok", "need_more_info"}:
        return "end"
    if retry_count >= 2:
        return "end"
    return "retry"


def legacy_plan(*, user_input: str, document_state=None, conversation_id=None) -> dict:
    """Plain replacement for the old LangGraph plan retry loop."""
    state = {
        "user_input": user_input,
        "document_state": document_state,
        "conversation_id": conversation_id,
        "retry_count": 0,
        "validation_errors": [],
    }
    if not (user_input or "").strip():
        return {"status": "error", "error_message": "用户输入为空", "plan_json": None}
    while True:
        suffix = ""
        if state["retry_count"] > 0 and state["validation_errors"]:
            suffix = "\n\n[系统反馈] 上一次生成的计划存在以下问题，请修正后重新生成：\n" + "".join(
                f"- {e}\n" for e in state["validation_errors"]
            )
        plan_json = generate_plan(user_input + suffix, document_state)
        state["plan_json"] = plan_json
        if plan_json and plan_json.get("status") == "need_more_info":
            state["status"] = "need_more_info"
        else:
            errors = _validate_plan(plan_json or {})
            state["validation_errors"] = errors
            state["status"] = "validation_failed" if errors else "ok"
            if errors:
                state["error_message"] = "; ".join(errors)
        if should_end(state) == "end":
            return state
        state["retry_count"] += 1


# ── node-shaped functions (thin wrappers for old call sites/tests) ─

def plan_next_step_node(state: dict) -> dict:
    session_id = state.get("session_id", "default")
    user_input = state["user_input"]
    high_level_plan = state.get("high_level_plan", {})
    current_phase_id = state.get("current_phase_id")
    document_state = state.get("document_state")
    execution_history = state.get("execution_history", {})
    name_map = state.get("name_map", {})
    abstract_step_queue = state.get("abstract_step_queue")
    current_abstract_step = state.get("current_abstract_step") or resolve_current_abstract_step(
        abstract_step_queue
    )

    if not current_phase_id:
        phases = high_level_plan.get("phases", [])
        if phases:
            current_phase_id = phases[0]["phase_id"]
        elif current_abstract_step:
            current_phase_id = current_abstract_step.get("step_id")
        else:
            return {
                "next_step_result": {"decision": "finish", "message": "没有可执行的阶段"},
                "status": "finished",
            }

    if abstract_step_queue and is_queue_exhausted(abstract_step_queue):
        return {
            "next_step_result": {
                "decision": "finish",
                "phase_id": current_phase_id,
                "tool_calls": [],
                "message": "计划阶段已全部完成",
            },
            "current_phase_id": current_phase_id,
            "status": "next_step_planned",
        }

    phase_id = current_abstract_step.get("step_id") if current_abstract_step else current_phase_id
    result = generate_next_tool_calls(
        session_id=session_id,
        user_input=user_input,
        high_level_plan=high_level_plan,
        current_phase_id=phase_id,
        document_state=document_state,
        execution_history=execution_history,
        name_map=name_map,
        session_memory=state.get("session_memory"),
    )
    if current_abstract_step:
        result["abstract_step_id"] = current_abstract_step.get("step_id")
        result["current_abstract_step"] = current_abstract_step
        result["recipe_id"] = (abstract_step_queue or {}).get("recipe_id")
    result["phase_id"] = phase_id

    return {"next_step_result": result, "current_phase_id": phase_id, "status": "next_step_planned"}


def validate_next_step_node(state: dict) -> dict:
    next_step_result = state.get("next_step_result", {})
    decision = next_step_result.get("decision", "")
    if decision in ("finish", "abort", "ask_user"):
        return {"status": "ok"}

    tool_calls = next_step_result.get("tool_calls", [])
    if not tool_calls:
        return {"status": "ok"}

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
        return {"status": "validation_failed", "error_message": "; ".join(errors)}

    query_errors = validate_query_before_act(
        tool_calls,
        state.get("execution_history") or {},
        session_memory=state.get("session_memory"),
        document_state=state.get("document_state"),
    )
    if query_errors:
        query_calls = build_required_query_calls(query_errors)
        next_step_result["decision"] = "execute"
        next_step_result["tool_calls"] = query_calls + tool_calls
        next_step_result["message"] = "需要先查询当前几何事实，再执行空间/拓扑敏感操作。"
        return {
            "status": "ok",
            "next_step_result": next_step_result,
            "validation_errors": query_errors,
            "query_required": True,
        }
    return {"status": "ok"}


def evaluate_step_node(state: dict) -> dict:
    from app.evaluation.rules import run_deterministic_checks
    from app.evaluation.validators import run_geometry_validators

    session_id = state.get("session_id", "default")
    last_tool_call = state.get("last_tool_call", {})
    execution_result = state.get("execution_result", {})
    document_state = state.get("document_state")
    execution_history = state.get("execution_history", {})
    high_level_plan = state.get("high_level_plan")
    current_phase_id = state.get("current_phase_id")
    before_state = state.get("before_state")
    current_recipe = state.get("current_recipe") or {}
    current_abstract_step = state.get("current_abstract_step") or {}
    abstract_step_queue = state.get("abstract_step_queue")
    strict_validation = bool(
        state.get("strict_validation")
        or current_recipe.get("strict_validation")
        or (high_level_plan or {}).get("strict_validation")
    )

    det_result = run_deterministic_checks(
        last_tool_call=last_tool_call,
        execution_result=execution_result,
        document_state=document_state,
    )
    is_query_execution = (
        execution_result.get("kind") == "query"
        or is_query_tool(last_tool_call.get("tool", ""))
    )
    skip_default_validators = _skip_default_object_validators(last_tool_call, execution_result)
    # 两种来源分开：模型在 expected_effect 里自己点名的验证器总是跑（它自己要求的检查，
    # 非阻断项只会变成 warning 回灌提示词）；配方/步骤的默认后置条件才归 strict 管，
    # 那些是系统强加的，全量打开容易触发修复循环。
    validator_names = []
    if not skip_default_validators:
        if strict_validation:
            validator_names = resolve_validator_names(current_abstract_step, current_recipe)
        expected_validators = (last_tool_call.get("expected_effect") or {}).get("validators") or []
        for name in expected_validators:
            if name not in validator_names:
                validator_names.append(name)
    validator_results = run_geometry_validators(
        validator_names,
        before_state=before_state,
        after_state=document_state,
        tool_call=last_tool_call,
        execution_result=execution_result,
    )
    from app.evaluation.validators import blocking_failures

    failed_validator_messages = blocking_failures(validator_results)
    if failed_validator_messages and det_result["passed"]:
        det_result = {
            "passed": False,
            "issues": failed_validator_messages,
            "suggested_decision": "repair",
        }

    result = evaluate_step_result(
        session_id=session_id,
        last_tool_call=last_tool_call,
        execution_result=execution_result,
        document_state=document_state,
        execution_history=execution_history,
        high_level_plan=high_level_plan,
        current_phase_id=current_phase_id,
        deterministic_checks=det_result,
        validator_results=validator_results,
        current_abstract_step=current_abstract_step or None,
        session_memory=state.get("session_memory"),
    )
    if result.get("repair_tool_calls"):
        result["repair_tool_calls"] = sanitize_tool_calls(result["repair_tool_calls"])
    result.setdefault("validator_results", validator_results)
    result.setdefault("postcondition_results", validator_results)
    if not det_result["passed"]:
        result.setdefault("deterministic_issues", det_result.get("issues", []))
        result["phase_status"] = "in_progress"
        result.pop("updated_current_phase_id", None)
        if result.get("decision") in {"finish", "abort"}:
            result["decision"] = "continue"
    from app.evaluation.validators import is_blocking_validator

    warning_validator_messages = [
        f"{item['validator']}:{item['error_code']}"
        for item in validator_results
        if not item.get("passed") and not is_blocking_validator(item)
    ]
    if warning_validator_messages:
        issues = result.setdefault("deterministic_issues", [])
        issues.extend([f"warning:{msg}" for msg in warning_validator_messages])

    if is_query_execution:
        result["decision"] = "continue"
        result["phase_status"] = "in_progress"
        result.pop("updated_current_phase_id", None)

    can_advance_success = (
        abstract_step_queue
        and current_abstract_step
        and det_result["passed"]
        and not is_query_execution
        and should_advance_abstract_step(
            execution_passed=True,
            validator_results=validator_results,
        )
    )
    can_advance_skip = (
        abstract_step_queue
        and current_abstract_step
        and not is_query_execution
        and not det_result["passed"]
        and (
            result.get("decision") == "skip_and_continue"
            or _consecutive_recent_errors(execution_history) >= 2
        )
    )
    if can_advance_success or can_advance_skip:
        advancement = apply_abstract_step_advancement(
            abstract_step_queue,
            current_abstract_step["step_id"],
        )
        result["abstract_step_queue"] = advancement["abstract_step_queue"]
        result["current_abstract_step"] = advancement["current_abstract_step"]
        result["abstract_step_completed"] = advancement["queue_completed"]
        result["phase_status"] = "completed"
        if advancement.get("updated_current_phase_id"):
            result["updated_current_phase_id"] = advancement["updated_current_phase_id"]
        if advancement["queue_completed"]:
            result["decision"] = "finish"
            result["message"] = result.get("message") or "All plan phases completed."
        else:
            result["decision"] = "continue"
            if can_advance_skip:
                result["message"] = (
                    result.get("message")
                    or f"跳过失败步骤 {current_abstract_step.get('step_id')}，进入下一 abstract step。"
                )

    if result.get("current_abstract_step") and result.get("decision") not in {"finish", "abort"}:
        if result.get("phase_status") != "completed":
            result["decision"] = "continue"
            result["phase_status"] = "in_progress"

    result = normalize_evaluate_decision(
        result,
        high_level_plan,
        current_phase_id,
        abstract_step_queue=result.get("abstract_step_queue") or abstract_step_queue,
    )

    active_queue = result.get("abstract_step_queue") or abstract_step_queue
    active_step = result.get("current_abstract_step") or resolve_current_abstract_step(active_queue)
    new_phase_id = result.get("updated_current_phase_id")
    updates = {
        "evaluate_result": result,
        "status": "evaluated",
        "abstract_step_queue": result.get("abstract_step_queue", abstract_step_queue),
    }
    if active_queue and isinstance(active_step, dict) and active_step.get("step_id"):
        updates["current_phase_id"] = (
            new_phase_id
            if result.get("phase_status") == "completed" and new_phase_id
            else active_step["step_id"]
        )
    elif new_phase_id:
        updates["current_phase_id"] = new_phase_id
    if "current_abstract_step" in result:
        updates["current_abstract_step"] = result.get("current_abstract_step")
    return updates
