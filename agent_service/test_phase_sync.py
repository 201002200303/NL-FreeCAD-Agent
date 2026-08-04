"""Phase pointer must follow abstract-step queue (no P3 work while stuck on P2)."""

from app.evaluation.phases import normalize_evaluate_decision, canonical_phase_id


def _queue(current="P2", completed=None):
    completed = set(completed or [])
    steps = []
    for pid, intent in (("P1", "主体"), ("P2", "倒角"), ("P3", "键槽")):
        steps.append({
            "step_id": pid,
            "step_type": "llm_phase",
            "intent": intent,
            "status": "completed" if pid in completed else "pending",
            "postconditions": ["verify_object_exists"],
            "expected_outputs": [],
            "input_refs": [],
            "allowed_tool_categories": [],
            "max_retry": 2,
            "risk_level": "medium",
        })
    return {
        "recipe_id": "llm_session",
        "steps": steps,
        "current_step_id": current,
    }


def test_llm_completed_without_queue_advance_does_not_jump_phase():
    """session_8287b1c5 class bug: LLM says completed→P3 while queue still on P2."""
    queue = _queue(current="P2", completed=["P1"])
    step = next(s for s in queue["steps"] if s["step_id"] == "P2")
    result = {
        "decision": "continue",
        "phase_status": "completed",
        "updated_current_phase_id": "P3",
        "message": "倒角完成，进入键槽",
        "current_abstract_step": step,
        "abstract_step_queue": queue,
    }
    out = normalize_evaluate_decision(
        result,
        {"phases": [{"phase_id": "P1"}, {"phase_id": "P2"}, {"phase_id": "P3"}]},
        "P2",
        abstract_step_queue=queue,
    )
    assert out["phase_status"] == "in_progress"
    assert out.get("updated_current_phase_id") in {None, "P2"}


def test_harness_advancement_keeps_next_step_as_phase():
    queue = _queue(current="P3", completed=["P1", "P2"])
    step = next(s for s in queue["steps"] if s["step_id"] == "P3")
    result = {
        "decision": "continue",
        "phase_status": "completed",
        "updated_current_phase_id": "P3",
        "current_abstract_step": step,
        "abstract_step_queue": queue,
    }
    out = normalize_evaluate_decision(
        result,
        {"phases": [{"phase_id": "P1"}, {"phase_id": "P2"}, {"phase_id": "P3"}]},
        "P2",
        abstract_step_queue=queue,
    )
    assert out["decision"] == "continue"
    assert out["updated_current_phase_id"] == "P3"
    assert out["phase_status"] == "completed"


def test_canonical_phase_id_prefers_abstract_step():
    assert canonical_phase_id(
        current_abstract_step={"step_id": "P2"},
        fallback="P3",
    ) == "P2"
