"""对话建模 + 视觉配置 + resume 旁白。"""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.conversation import conversation_scope
from app.conversation.notes import format_resume_note
from app.conversation.store import ConversationStore
from app.main import app
from app.vision.service import format_vision_for_prompt, vision_available
from app.workflow import chat as chat_mod


client = TestClient(app)


@pytest.fixture
def conv_store(monkeypatch):
    db = Path(tempfile.mkdtemp(prefix="nlfc_chat_")) / "c.db"
    store = ConversationStore(db)
    monkeypatch.setattr("app.conversation._store", store)
    return store


def test_capabilities_exposes_vision_and_chat():
    r = client.get("/agent/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["chat"] is True
    assert "vision" in body
    assert "enabled" in body["vision"]
    assert "plan_mode_default" in body


def test_resume_note_lists_removed_objects():
    note = format_resume_note(
        {
            "changed": True,
            "added": [{"name": "Wheel_R"}],
            "removed": [{"name": "Body"}],
            "modified": [],
            "summary": "手工改过",
        }
    )
    assert "Body" in note and "Wheel_R" in note
    assert "会话中断恢复" in note


def test_resume_note_empty_when_unchanged():
    assert format_resume_note(None) == ""
    assert format_resume_note({"changed": False}) == ""


def test_resume_endpoint_writes_transcript_note(conv_store, monkeypatch):
    from app.runtime import get_runtime

    rt = get_runtime()
    sid = "resume_chat_1"
    rt.start_session(sid, user_input="建个箱子", goal="box")
    # seed a prior turn
    with conversation_scope(sid) as t:
        t.append_turn("建个箱子", '{"message":"ok"}')

    monkeypatch.setattr(
        "app.runtime.service.diff_documents",
        lambda ref, cur: {
            "changed": True,
            "added": [],
            "removed": [{"name": "Box"}],
            "modified": [],
            "summary": "删除了 Box",
        },
    )
    # pause with snapshot then resume with different doc
    rt.pause_session(
        sid,
        document_state={"objects": [{"name": "Box"}]},
        reason="test",
    )
    r = client.post(
        f"/agent/session/{sid}/resume",
        json={"document_state": {"objects": []}},
    )
    assert r.status_code == 200
    msgs = "\n".join(m["content"] for m in conv_store.load(sid).messages)
    assert "会话中断恢复" in msgs or "Box" in msgs


def test_vision_unavailable_without_model(monkeypatch):
    monkeypatch.setattr("app.config.VISION_ENABLED", True)
    monkeypatch.setattr("app.config.VISION_API_KEY", "k")
    monkeypatch.setattr("app.config.VISION_MODEL", "")
    assert vision_available() is False


def test_vision_respects_server_kill_switch(monkeypatch):
    monkeypatch.setattr("app.config.VISION_ENABLED", False)
    monkeypatch.setattr("app.config.VISION_API_KEY", "k")
    monkeypatch.setattr("app.config.VISION_MODEL", "gpt-4o")
    assert vision_available(request_enabled=True) is False


def test_format_vision_for_prompt():
    text = format_vision_for_prompt(
        {"skipped": False, "verdict": "warn", "summary": "左轮悬空", "issues": ["gap"], "suggestions": ["贴地"]}
    )
    assert "左轮悬空" in text and "warn" in text


def test_chat_turn_records_transcript(conv_store, monkeypatch):
    monkeypatch.setattr(
        chat_mod,
        "call_llm",
        lambda *a, **k: {
            "message": "先建车身",
            "tool_calls": [
                {
                    "call_id": "T1",
                    "tool": "create_box",
                    "args": {"name": "Body", "length": 10, "width": 10, "height": 10},
                    "description": "车身",
                }
            ],
            "status": "awaiting_tools",
            "soft_plan": {"items": [{"id": "1", "title": "车身", "status": "in_progress"}]},
        },
    )
    monkeypatch.setattr(chat_mod, "vision_available", lambda **kw: False)

    result = chat_mod.chat_turn(
        session_id="chat1",
        message="做一辆小车",
        document_state=None,
        plan_mode=True,
        vision_enabled=False,
    )
    assert result["status"] == "awaiting_tools"
    assert result["tool_calls"][0]["tool"] == "create_box"
    assert "车身" in result["message"]
    assert conv_store.message_count("chat1") >= 2


def test_chat_endpoint_smoke(conv_store, monkeypatch):
    monkeypatch.setattr(
        chat_mod,
        "call_llm",
        lambda *a, **k: {
            "message": "好的，轮距改成 1600",
            "tool_calls": [],
            "status": "awaiting_user",
        },
    )
    monkeypatch.setattr(chat_mod, "vision_available", lambda **kw: False)
    r = client.post(
        "/agent/chat",
        json={"message": "轮距改成 1600mm", "plan_mode": True, "vision_enabled": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "awaiting_user"
    assert body["session_id"]
    assert "1600" in body["message"]


def test_compress_keeps_head_and_recent(conv_store, monkeypatch):
    sid = "cmp1"
    with conversation_scope(sid) as t:
        t.append_turn("原始需求：总长4500", '{"message":"收到"}')
        for i in range(10):
            t.append_turn(f"中间{i}", f'{{"message":"m{i}"}}')
        t.append_turn("最近一轮", '{"message":"recent"}')

    monkeypatch.setattr(chat_mod, "_call_text_llm", lambda s, u: "摘要：做过车身和轮子")
    result = chat_mod.compress_context(sid, keep_recent_turns=2)
    assert result["status"] == "ok"
    msgs = conv_store.load(sid).messages
    joined = "\n".join(m["content"] for m in msgs)
    assert "原始需求：总长4500" in joined
    assert "上下文已压缩" in joined
    assert "最近一轮" in joined
