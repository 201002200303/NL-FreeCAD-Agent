"""Unit tests for durable runtime event log + checkpoint."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.runtime.events import EventType
from app.runtime.service import RuntimeService, reset_runtime_for_tests
from app.runtime.context import build_llm_context


def _temp_db() -> Path:
    return Path(tempfile.mkdtemp(prefix="nlfc_runtime_")) / "runtime.db"


def test_event_log_and_checkpoint_roundtrip():
    db = _temp_db()
    rt = reset_runtime_for_tests(db)

    ckpt = rt.start_session(
        "session_test01",
        user_input="做一个小车",
        goal="小车模型",
        plan={
            "goal": "小车模型",
            "phases": [
                {"phase_id": "P1", "title": "车身", "intent": "车身主体"},
                {"phase_id": "P2", "title": "车轮", "intent": "四个车轮"},
            ],
        },
        document_state={"document_name": "Unnamed", "objects": []},
    )
    assert ckpt["checkpoint_id"]
    assert ckpt["status"] == "running"

    rt.record_next_step(
        "session_test01",
        phase_id="P1",
        decision="execute",
        tool_calls=[
            {
                "call_id": "P1_S1",
                "tool": "create_box",
                "args": {"name": "Body", "length": 100, "width": 40, "height": 20},
            }
        ],
        message="先做车身",
        current_abstract_step={"step_id": "P1", "intent": "车身主体"},
    )
    rt.record_tool_result(
        "session_test01",
        tool_call={"call_id": "P1_S1", "tool": "create_box"},
        execution_result={
            "status": "success",
            "tool": "create_box",
            "produced_objects": ["Body"],
        },
        phase_id="P1",
        document_state={
            "document_name": "Unnamed",
            "objects": [
                {
                    "name": "Body",
                    "type": "Part::Box",
                    "bbox": {"size": [100, 40, 20], "center": [0, 0, 10]},
                    "topology": {"solids": 1},
                }
            ],
        },
    )
    rt.record_evaluate(
        "session_test01",
        evaluate_result={
            "decision": "continue",
            "phase_status": "completed",
            "updated_current_phase_id": "P2",
            "message": "车身完成",
        },
        phase_id="P1",
        high_level_plan={"goal": "小车模型"},
        abstract_step_queue={"current_step_id": "P2"},
        current_abstract_step={"step_id": "P2", "intent": "四个车轮"},
        session_memory={
            "object_memory": {"Body": {"type": "Part::Box", "role": "chassis", "size": [100, 40, 20]}},
            "error_memory": {},
            "progress": {"goal": "小车模型"},
        },
    )

    events = rt.store.list_events("session_test01")
    types = [e["event_type"] for e in events]
    assert EventType.SESSION_STARTED in types
    assert EventType.PLAN_CREATED in types
    assert EventType.TOOL_STARTED in types
    assert EventType.TOOL_SUCCEEDED in types
    assert EventType.STEP_COMPLETED in types
    assert EventType.CHECKPOINT_SAVED in types

    latest = rt.load_checkpoint("session_test01")
    assert latest is not None
    assert latest["run_state"]["current_phase_id"] == "P2"
    assert latest["run_state"]["session_memory"]["object_memory"]["Body"]["role"] == "chassis"

    rt2 = RuntimeService(db)
    recovered = rt2.load_checkpoint("session_test01")
    assert recovered["run_state"]["current_phase_id"] == "P2"
    assert rt2.store.latest_seq("session_test01") >= 5


def test_context_slice_includes_related_objects_and_errors():
    db = _temp_db()
    rt = reset_runtime_for_tests(db)
    rt.start_session("session_ctx", user_input="小车", goal="小车", plan={"goal": "小车", "phases": []})
    rt.record_tool_result(
        "session_ctx",
        tool_call={"call_id": "P1_S1", "tool": "create_cylinder"},
        execution_result={"status": "error", "tool": "create_cylinder", "message": "bad args"},
        phase_id="P1",
    )
    slice_ = rt.build_context_slice(
        "session_ctx",
        document_state={
            "document_name": "Doc",
            "objects": [
                {
                    "name": "Chassis_Pad",
                    "type": "PartDesign::Pad",
                    "bbox": {"size": [190, 100, 50], "center": [0, 0, 25]},
                    "topology": {"solids": 1},
                }
            ],
        },
        session_memory={
            "object_memory": {"Chassis_Pad": {"role": "chassis", "type": "PartDesign::Pad"}},
            "error_memory": {"last_error": {"tool": "create_cylinder", "message": "bad args"}},
            "current_target": "Chassis_Pad",
        },
        current_phase_id="P2",
        current_abstract_step={"step_id": "P2", "intent": "车轮"},
    )
    assert slice_["unresolved_errors"]
    assert any(obj["name"] == "Chassis_Pad" for obj in slice_["related_cad_objects"])

    text = build_llm_context(
        session_id="session_ctx",
        user_input="小车",
        goal="小车",
        session_memory={
            "working_summary": "目标: 小车",
            "object_memory": {"Chassis_Pad": {"role": "chassis"}},
            "error_memory": {"last_error": {"tool": "create_cylinder", "message": "bad args"}},
            "progress": {"current_phase_id": "P2"},
        },
        current_phase_id="P2",
        current_abstract_step={"step_id": "P2", "intent": "车轮"},
    )
    assert "Runtime State" in text
    assert "未解决错误" in text
