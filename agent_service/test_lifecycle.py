"""Lifecycle / pause-resume / reducer / document diff tests (no FreeCAD)."""

import shutil
import tempfile
from pathlib import Path

import pytest

from app.runtime.diff import compact_objects, diff_documents
from app.runtime.events import EventType
from app.runtime.reducer import reduce_events
from app.runtime.service import reset_runtime_for_tests


@pytest.fixture
def runtime():
    # Avoid pytest tmpdir PermissionError on some Windows setups
    root = Path(tempfile.mkdtemp(prefix="cad_runtime_"))
    try:
        yield reset_runtime_for_tests(root / "lifecycle.db")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _doc(*names):
    return {
        "document_name": "Doc",
        "objects": [
            {
                "name": n,
                "type": "Part::Box",
                "visible": True,
                "bbox": {
                    "xmin": 0,
                    "xmax": 10,
                    "ymin": 0,
                    "ymax": 10,
                    "zmin": 0,
                    "zmax": 10,
                    "size": [10, 10, 10],
                    "center": [5, 5, 5],
                },
                "placement": {"base": [0, 0, 0]},
            }
            for n in names
        ],
    }


def test_pause_writes_event_and_checkpoint(runtime):
    sid = "sess_pause"
    runtime.start_session(sid, user_input="make a car", goal="car", plan={"phases": []}, document_state=_doc("A"))
    ckpt = runtime.pause_session(sid, document_state=_doc("A"), reason="user_pause")
    assert ckpt["status"] == "paused"
    assert ckpt["run_state"].get("paused_document_objects")
    events = runtime.store.list_events(sid)
    assert any(e["event_type"] == EventType.USER_PAUSED for e in events)


def test_resume_detects_user_changes(runtime):
    sid = "sess_resume"
    runtime.start_session(sid, user_input="x", goal="x", plan={}, document_state=_doc("A"))
    runtime.pause_session(sid, document_state=_doc("A"))
    result = runtime.resume_session(sid, document_state=_doc("A", "B"))
    assert result["document_changes"]["changed"] is True
    assert "B" in result["document_changes"]["added"]
    events = runtime.store.list_events(sid)
    types = [e["event_type"] for e in events]
    assert EventType.DOCUMENT_CHANGED_BY_USER in types
    assert EventType.USER_RESUMED in types


def test_resume_replays_post_checkpoint_events(runtime):
    sid = "sess_replay"
    runtime.start_session(sid, user_input="x", goal="x", plan={}, document_state=_doc("A"))
    ckpt = runtime.pause_session(sid, document_state=_doc("A"))
    after = ckpt["event_seq"]
    runtime.store.append_event(
        sid,
        EventType.TOOL_SUCCEEDED,
        action_id="act_X",
        payload={"tool": "create_box", "status": "success"},
    )
    # Ensure event is after checkpoint seq
    events_after = runtime.store.list_events(sid, after_seq=after)
    assert any(e["action_id"] == "act_X" for e in events_after)
    result = runtime.resume_session(sid, document_state=_doc("A"))
    assert "act_X" in result["run_state"]["completed_action_ids"]


def test_reducer_rebuilds_state():
    base = {"completed_action_ids": [], "pending_action_ids": []}
    events = [
        {"event_type": EventType.TOOL_STARTED, "action_id": "a1", "payload": {}},
        {
            "event_type": EventType.TOOL_SUCCEEDED,
            "action_id": "a1",
            "payload": {"document_revision": "rev1"},
        },
        {
            "event_type": EventType.TOOL_FAILED,
            "action_id": "a2",
            "payload": {"tool": "move", "message": "fail"},
            "phase_id": "P1",
        },
        {"event_type": EventType.USER_PAUSED, "payload": {}},
    ]
    state = reduce_events(base, events)
    assert "a1" in state["completed_action_ids"]
    assert "a2" not in state["pending_action_ids"]
    assert state["status"] == "paused"
    assert state["unresolved_errors"]
    assert state["document_revision"] == "rev1"


def test_diff_documents():
    before = compact_objects(_doc("A", "B"))
    after_objs = compact_objects(_doc("A", "C"))
    # modify A position in after
    after_objs[0]["pos"] = [1, 0, 0]
    after_objs[0]["center"] = [6, 5, 5]
    result = diff_documents(before, after_objs)
    assert result["changed"]
    assert "C" in result["added"]
    assert "B" in result["removed"]
    assert any(m["name"] == "A" and "position" in m["changes"] for m in result["modified"])


def test_session_snapshot_and_list(runtime):
    sid = "sess_snap"
    runtime.start_session(sid, user_input="hello", goal="goal", plan={"phases": [{"phase_id": "P1"}]})
    runtime.pause_session(sid, document_state=_doc("A"))
    snap = runtime.get_session_snapshot(sid)
    assert snap is not None
    assert snap["session"]["session_id"] == sid
    assert snap["run_state"]
    listed = runtime.list_sessions(limit=5)
    assert any(s["session_id"] == sid for s in listed)
