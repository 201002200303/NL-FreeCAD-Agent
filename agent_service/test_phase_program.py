from app.phase_program import (
    prepare_phase_tool_calls,
    reconcile_soft_plan,
    reduce_phase_feedback,
)
from app.schemas.request import ChatRequest
from app.schemas.response import ChatResponse


def _plan():
    return {
        "items": [
            {
                "id": "P1",
                "title": "建立主体",
                "status": "in_progress",
                "acceptance": [
                    {"type": "object_exists", "target": "Main"},
                    {"type": "valid_shape", "target": "Main"},
                    {"type": "solid_count", "target": "Main", "equals": 1},
                    {
                        "type": "bbox_size",
                        "target": "Main",
                        "value": [100, 60, 20],
                        "tolerance": 0.1,
                    },
                ],
            },
            {"id": "P2", "title": "添加孔槽", "status": "pending"},
        ]
    }


def _document(valid=True):
    return {
        "document_name": "Doc",
        "objects": [
            {
                "name": "Main",
                "label": "Main",
                "type": "Part::Feature",
                "visible": True,
                "bbox": {"size": [100.0, 60.0, 20.0], "center": [0, 0, 10]},
                "topology": {
                    "faces": 6,
                    "edges": 12,
                    "vertices": 8,
                    "solids": 1,
                    "is_valid": valid,
                    "volume": 120000.0,
                },
                "properties": {},
            }
        ],
    }


def test_prepare_phase_program_adds_host_identity_and_acceptance():
    calls = [
        {
            "call_id": "T1",
            "tool": "execute_cad_program",
            "args": {"code": "x = cad.box(name='Main', size=(1,1,1), center=(0,0,0))\r\n"},
        }
    ]
    prepared, state = prepare_phase_tool_calls(
        calls, session_id="S1", soft_plan=_plan(), phase_state=None
    )

    args = prepared[0]["args"]
    assert args["phase_id"] == "P1"
    assert args["acceptance"][0]["type"] == "object_exists"
    assert len(args["program_hash"]) == 64
    assert args["execution_key"].startswith("S1:P1:")
    assert state["status"] == "awaiting_execution"
    assert state["program_hash"] == args["program_hash"]


def test_successful_receipt_and_acceptance_advance_the_phase():
    plan = _plan()
    calls, waiting = prepare_phase_tool_calls(
        [{"call_id": "T1", "tool": "execute_cad_program", "args": {"code": "pass"}}],
        session_id="S1",
        soft_plan=plan,
        phase_state=None,
    )
    results = [
        {
            "tool_call": calls[0],
            "execution_result": {
                "status": "success",
                "tool": "execute_cad_program",
                "produced_objects": ["Main"],
                "program_hash": calls[0]["args"]["program_hash"],
                "execution_key": calls[0]["args"]["execution_key"],
                "state_diff": {"changed": True, "added": ["Main"], "removed": [], "modified": []},
            },
        }
    ]

    reduced = reduce_phase_feedback(plan, results, _document(), waiting)

    assert reduced.phase_state["status"] == "passed"
    assert all(check["passed"] for check in reduced.phase_state["checks"])
    assert reduced.soft_plan["items"][0]["status"] == "done"
    assert reduced.soft_plan["items"][1]["status"] == "in_progress"


def test_failed_acceptance_keeps_current_phase_in_progress():
    plan = _plan()
    calls, waiting = prepare_phase_tool_calls(
        [{"call_id": "T1", "tool": "execute_cad_program", "args": {"code": "pass"}}],
        session_id="S1",
        soft_plan=plan,
        phase_state=None,
    )
    results = [
        {
            "tool_call": calls[0],
            "execution_result": {
                "status": "success",
                "tool": "execute_cad_program",
                "produced_objects": ["Main"],
                "state_diff": {"changed": True, "added": ["Main"]},
            },
        }
    ]

    reduced = reduce_phase_feedback(plan, results, _document(valid=False), waiting)

    assert reduced.phase_state["status"] == "failed"
    assert reduced.soft_plan["items"][0]["status"] == "in_progress"
    assert reduced.soft_plan["items"][1]["status"] == "pending"
    assert any(not check["passed"] for check in reduced.phase_state["checks"])


def test_llm_cannot_mark_a_phase_done_without_host_gate():
    host_plan = _plan()
    proposed = _plan()
    proposed["items"][0]["status"] = "done"
    proposed["items"][1]["status"] = "in_progress"

    reconciled = reconcile_soft_plan(proposed, host_plan, phase_state={"phase_id": "P1", "status": "failed"})

    assert reconciled["items"][0]["status"] == "in_progress"
    assert reconciled["items"][1]["status"] == "pending"


def test_execution_error_never_advances_phase():
    plan = _plan()
    reduced = reduce_phase_feedback(
        plan,
        [
            {
                "tool_call": {"tool": "execute_cad_program", "args": {"phase_id": "P1"}},
                "execution_result": {"status": "error", "message": "boolean failed"},
            }
        ],
        _document(),
        {"phase_id": "P1", "status": "awaiting_execution", "attempt": 1},
    )

    assert reduced.phase_state["status"] == "failed"
    assert reduced.phase_state["error"] == "boolean failed"
    assert reduced.soft_plan["items"][0]["status"] == "in_progress"


def test_awaiting_execution_marks_planned_phase_in_progress():
    plan = _plan()
    plan["items"][0]["status"] = "pending"
    reconciled = reconcile_soft_plan(
        plan,
        plan,
        phase_state={"phase_id": "P1", "status": "awaiting_execution"},
    )
    assert reconciled["items"][0]["status"] == "in_progress"


def test_phase_state_round_trips_through_chat_schemas():
    phase_state = {"phase_id": "P1", "status": "awaiting_execution", "attempt": 1}
    request = ChatRequest(message="继续", phase_state=phase_state)
    response = ChatResponse(
        status="awaiting_user", session_id="S1", phase_state=request.phase_state
    )
    assert response.model_dump()["phase_state"] == phase_state
