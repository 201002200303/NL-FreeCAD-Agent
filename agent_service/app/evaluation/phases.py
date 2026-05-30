"""Phase progression helpers for closed-loop execution."""


def get_phase_ids(high_level_plan: dict | None) -> list[str]:
    if not high_level_plan:
        return []
    phases = high_level_plan.get("phases", [])
    return [p["phase_id"] for p in phases if isinstance(p, dict) and p.get("phase_id")]


def get_next_phase_id(high_level_plan: dict | None, current_phase_id: str | None) -> str | None:
    if not high_level_plan or not current_phase_id:
        return None
    ids = get_phase_ids(high_level_plan)
    try:
        idx = ids.index(current_phase_id)
    except ValueError:
        return None
    if idx + 1 < len(ids):
        return ids[idx + 1]
    return None


def is_last_phase(high_level_plan: dict | None, current_phase_id: str | None) -> bool:
    ids = get_phase_ids(high_level_plan)
    return bool(ids) and bool(current_phase_id) and ids[-1] == current_phase_id


def format_phases_overview(high_level_plan: dict | None, current_phase_id: str | None) -> str:
    if not high_level_plan:
        return ""
    lines = ["## 高层计划阶段概览"]
    for phase in high_level_plan.get("phases", []):
        pid = phase.get("phase_id", "?")
        marker = " ← 当前" if pid == current_phase_id else ""
        lines.append(f"- {pid}: {phase.get('title', '')} — {phase.get('intent', '')}{marker}")
    lines.append(
        "\n**重要**: 只有所有阶段都完成后才能 decision=finish。"
        "当前阶段完成后必须进入下一阶段，不能提前结束整个任务。"
    )
    return "\n".join(lines)


def normalize_evaluate_decision(
    result: dict,
    high_level_plan: dict | None,
    current_phase_id: str | None,
) -> dict:
    """Prevent premature finish when more phases remain."""
    if not high_level_plan or not current_phase_id:
        return result

    out = dict(result)
    decision = out.get("decision", "continue")
    phase_status = out.get("phase_status", "in_progress")
    next_phase = get_next_phase_id(high_level_plan, current_phase_id)

    # LLM declared finish but more phases remain → advance phase, keep going
    if decision == "finish" and next_phase:
        out["decision"] = "continue"
        out["phase_status"] = "completed"
        out["updated_current_phase_id"] = next_phase
        msg = out.get("message") or ""
        out["message"] = f"阶段 {current_phase_id} 完成，进入 {next_phase}。{msg}".strip()
        return out

    # Phase marked completed → advance to next phase if any
    if phase_status == "completed" and next_phase:
        out["decision"] = "continue"
        out["updated_current_phase_id"] = next_phase
        if not out.get("message"):
            out["message"] = f"阶段 {current_phase_id} 完成，进入 {next_phase}"

    # Last phase done → allow finish
    if is_last_phase(high_level_plan, current_phase_id):
        if phase_status == "completed" or decision == "finish":
            out["decision"] = "finish"
            out["phase_status"] = "completed"

    return out


def normalize_next_step_decision(
    result: dict,
    high_level_plan: dict | None,
    current_phase_id: str | None,
) -> tuple[dict, str | None]:
    """Prevent next_step from finishing early. Returns (result, advanced_phase_id)."""
    if not high_level_plan or not current_phase_id:
        return result, None

    out = dict(result)
    decision = out.get("decision", "execute")
    next_phase = get_next_phase_id(high_level_plan, current_phase_id)

    if decision == "finish" and next_phase:
        out["decision"] = "execute"
        out["phase_id"] = next_phase
        out["tool_calls"] = []
        out["message"] = f"阶段 {current_phase_id} 已完成，自动进入 {next_phase}"
        return out, next_phase

    return out, None
