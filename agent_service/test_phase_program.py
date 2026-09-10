from app.phase_program import (
    mark_current_phase,
    prepare_phase_tool_calls,
    reconcile_soft_plan,
    reduce_phase_feedback,
)
from app.phase_program.acceptance import evaluate_acceptance
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


def test_llm_cannot_mark_phase_done_without_any_phase_state():
    """D2: 空 phase_state 不是绕过宿主计划状态的许可证。"""
    host_plan = _plan()
    proposed = _plan()
    proposed["items"][0]["status"] = "done"
    proposed["items"][1]["status"] = "done"

    reconciled = reconcile_soft_plan(proposed, host_plan, phase_state=None)

    assert reconciled["items"][0]["status"] == "in_progress"
    assert reconciled["items"][1]["status"] == "pending"


def test_first_turn_without_host_plan_accepts_agent_plan():
    """首轮没有宿主计划时，模型计划可以成为宿主计划。"""
    reconciled = reconcile_soft_plan(_plan(), None, phase_state=None)

    assert reconciled["items"][0]["status"] == "in_progress"
    assert reconciled["items"][1]["status"] == "pending"


def test_host_phases_survive_agent_renamed_plan():
    """换一套阶段 id 不能把宿主计划挤掉、也不能自称 done。"""
    host_plan = _plan()
    proposed = {"items": [{"id": "PX", "title": "全新阶段", "status": "done"}]}

    reconciled = reconcile_soft_plan(proposed, host_plan, phase_state=None)

    statuses = {item["id"]: item["status"] for item in reconciled["items"]}
    assert statuses["P1"] == "in_progress"
    assert statuses["P2"] == "pending"
    assert statuses["PX"] == "pending"


def test_mark_current_phase_maps_awaiting_execution_to_in_progress():
    plan = _plan()
    plan["items"][0]["status"] = "pending"

    marked = mark_current_phase(plan, {"phase_id": "P1", "status": "awaiting_execution"})

    assert marked["items"][0]["status"] == "in_progress"


def test_mark_current_phase_marks_passed_phase_done():
    plan = _plan()

    marked = mark_current_phase(plan, {"phase_id": "P1", "status": "passed"})

    assert marked["items"][0]["status"] == "done"


def _success_receipt(call):
    return [
        {
            "tool_call": call,
            "execution_result": {
                "status": "success",
                "tool": "execute_cad_program",
                "produced_objects": ["Main"],
                "program_hash": (call.get("args") or {}).get("program_hash"),
                "execution_key": (call.get("args") or {}).get("execution_key"),
                "state_diff": {"changed": True, "added": ["Main"], "removed": [], "modified": []},
            },
        }
    ]


def _prepare(plan, phase_state=None):
    return prepare_phase_tool_calls(
        [{"call_id": "T1", "tool": "execute_cad_program", "args": {"code": "pass"}}],
        session_id="S1",
        soft_plan=plan,
        phase_state=phase_state,
    )


def test_prepare_freezes_acceptance_into_phase_state():
    calls, state = _prepare(_plan())

    assert state["acceptance"] == _plan()["items"][0]["acceptance"]
    assert calls[0]["args"]["acceptance"] == state["acceptance"]


def test_agent_cannot_relax_locked_acceptance():
    _, waiting = _prepare(_plan())
    weakened = _plan()
    weakened["items"][0]["acceptance"] = [{"type": "object_exists", "target": "Main"}]

    calls, state = _prepare(weakened, waiting)

    types = {check["type"] for check in state["acceptance"]}
    assert {"valid_shape", "solid_count", "bbox_size"} <= types
    assert {"valid_shape", "solid_count", "bbox_size"} <= {
        check["type"] for check in calls[0]["args"]["acceptance"]
    }


def test_agent_can_add_acceptance_but_not_drop_locked_checks():
    _, waiting = _prepare(_plan())
    extended = _plan()
    extended["items"][0]["acceptance"] = [
        {"type": "object_exists", "target": "Main"},
        {"type": "volume_range", "target": "Main", "min": 100000, "max": 150000},
    ]

    _, state = _prepare(extended, waiting)

    types = [check["type"] for check in state["acceptance"]]
    assert "volume_range" in types
    assert "bbox_size" in types and "solid_count" in types


def test_relaxed_tolerance_cannot_override_locked_check():
    _, waiting = _prepare(_plan())
    relaxed = _plan()
    relaxed["items"][0]["acceptance"] = [
        {"type": "bbox_size", "target": "Main", "value": [100, 60, 20], "tolerance": 50.0}
    ]

    _, state = _prepare(relaxed, waiting)

    tolerances = [
        check["tolerance"]
        for check in state["acceptance"]
        if check["type"] == "bbox_size"
    ]
    assert 0.1 in tolerances
    evaluated = evaluate_acceptance(state["acceptance"], _document())
    assert any(not check["passed"] for check in evaluated) or all(
        check["passed"] for check in evaluated
    )
    strict = [c for c in evaluated if c["type"] == "bbox_size" and c["tolerance"] == 0.1]
    assert strict and strict[0]["passed"] is True


def test_phase_without_acceptance_cannot_pass():
    plan = _plan()
    plan["items"][0]["acceptance"] = []
    calls, waiting = _prepare(plan)

    reduced = reduce_phase_feedback(plan, _success_receipt(calls[0]), _document(), waiting)

    assert reduced.phase_state["status"] == "failed"
    assert "acceptance" in (reduced.phase_state["error"] or "")
    assert reduced.soft_plan["items"][0]["status"] == "in_progress"


def test_phase_without_geometric_check_cannot_pass():
    plan = _plan()
    plan["items"][0]["acceptance"] = [{"type": "object_exists", "target": "Main"}]
    calls, waiting = _prepare(plan)

    reduced = reduce_phase_feedback(plan, _success_receipt(calls[0]), _document(), waiting)

    assert reduced.phase_state["status"] == "failed"
    assert "geometric" in (reduced.phase_state["error"] or "")


def test_ad_hoc_phase_keeps_default_checks():
    """没有 soft_plan 的临时建模不因新规被卡死。"""
    calls = [
        {
            "call_id": "T1",
            "tool": "execute_cad_program",
            "args": {"code": "pass", "phase_id": "ad_hoc", "acceptance": []},
        }
    ]
    reduced = reduce_phase_feedback(
        None,
        _success_receipt(calls[0]),
        _document(),
        {"phase_id": "ad_hoc", "status": "awaiting_execution", "attempt": 1},
    )

    assert reduced.phase_state["status"] == "passed"


def test_phase_state_round_trips_through_chat_schemas():
    phase_state = {"phase_id": "P1", "status": "awaiting_execution", "attempt": 1}
    request = ChatRequest(message="继续", phase_state=phase_state)
    response = ChatResponse(
        status="awaiting_user", session_id="S1", phase_state=request.phase_state
    )
    assert response.model_dump()["phase_state"] == phase_state
