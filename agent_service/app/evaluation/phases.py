"""Phase progression helpers for closed-loop execution."""

from app.abstract_steps.planner import resolve_current_abstract_step


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


def canonical_phase_id(
    abstract_step_queue: dict | None = None,
    current_abstract_step: dict | None = None,
    fallback: str | None = None,
) -> str | None:
    """Single source of truth: active abstract step id, else fallback."""
    step = current_abstract_step or resolve_current_abstract_step(abstract_step_queue)
    if isinstance(step, dict) and step.get("step_id"):
        return step["step_id"]
    return fallback


def normalize_evaluate_decision(
    result: dict,
    high_level_plan: dict | None,
    current_phase_id: str | None,
    *,
    abstract_step_queue: dict | None = None,
) -> dict:
    """Prevent premature finish / phase drift when abstract-step queue drives control."""
    out = dict(result)
    if out.get("abstract_step_completed"):
        out["decision"] = "finish"
        out["phase_status"] = "completed"
        return out

    queue = out.get("abstract_step_queue") or abstract_step_queue
    step = out.get("current_abstract_step")
    resolved = step or (resolve_current_abstract_step(queue) if queue else None)

    # Queue-driven track: phase pointer is derived from abstract step only.
    if queue:
        if resolved and out.get("decision") == "finish":
            out["decision"] = "continue"
            out["updated_current_phase_id"] = resolved.get("step_id")
            if step is None:
                out["current_abstract_step"] = resolved
            return out

        if not resolved:
            return out

        sid = resolved.get("step_id")
        updated = out.get("updated_current_phase_id")
        # Real advancement: harness moved current_abstract_step to the next id.
        advanced = (
            out.get("phase_status") == "completed"
            and updated == sid
            and bool(sid)
            and sid != current_phase_id
            and step is not None  # only trust when evaluate/harness supplied the step
        )
        if advanced:
            out["decision"] = "continue"
            out["updated_current_phase_id"] = sid
            return out

        # LLM claimed phase complete / jumped ahead without queue advancement → stay.
        if out.get("phase_status") == "completed" and not advanced:
            out["phase_status"] = "in_progress"
            out.pop("updated_current_phase_id", None)
        elif updated and sid and updated != sid:
            out.pop("updated_current_phase_id", None)
        return out

    # Legacy high-level-only path (no abstract-step queue).
    next_abstract = out.get("current_abstract_step")
    if next_abstract and out.get("decision") == "finish":
        out["decision"] = "continue"
        out["phase_status"] = "completed"
        if not out.get("updated_current_phase_id"):
            out["updated_current_phase_id"] = next_abstract.get("step_id")
        return out

    if not high_level_plan or not current_phase_id:
        return out
    decision = out.get("decision", "continue")
    phase_status = out.get("phase_status", "in_progress")
    next_phase = get_next_phase_id(high_level_plan, current_phase_id)

    if decision == "finish" and next_phase:
        out["decision"] = "continue"
        out["phase_status"] = "completed"
        out["updated_current_phase_id"] = next_phase
        msg = out.get("message") or ""
        out["message"] = f"阶段 {current_phase_id} 完成，进入 {next_phase}。{msg}".strip()
        return out

    if phase_status == "completed" and next_phase:
        out["decision"] = "continue"
        out["updated_current_phase_id"] = next_phase
        if not out.get("message"):
            out["message"] = f"阶段 {current_phase_id} 完成，进入 {next_phase}"

    if is_last_phase(high_level_plan, current_phase_id) and not next_abstract:
        if phase_status == "completed" or decision == "finish":
            out["decision"] = "finish"
            out["phase_status"] = "completed"

    return out


def normalize_next_step_decision(
    result: dict,
    high_level_plan: dict | None,
    current_phase_id: str | None,
) -> tuple[dict, str | None]:
    """Keep next_step on the current phase; evaluate/harness owns phase advances.

    Returns (result, advanced_phase_id). advanced_phase_id is always None now —
    kept for call-site compatibility.
    """
    if not high_level_plan or not current_phase_id:
        return result, None

    out = dict(result)
    decision = out.get("decision", "execute")
    next_phase = get_next_phase_id(high_level_plan, current_phase_id)

    # Do not let next_step jump phases; that desyncs abstract_step_queue.
    if decision == "finish" and next_phase:
        out["decision"] = "execute"
        out["phase_id"] = current_phase_id
        msg = out.get("message") or ""
        out["message"] = (
            f"{msg}（阶段切换由 evaluate 确认，请继续当前阶段 {current_phase_id}）"
        ).strip()
        return out, None

    out["phase_id"] = current_phase_id
    return out, None
