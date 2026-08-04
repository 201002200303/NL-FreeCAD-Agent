"""对话累积：Transcript 修剪、持久化、与 call_llm 的接线。"""

import tempfile
from pathlib import Path

import pytest

from app.conversation import conversation_scope, active_transcript
from app.conversation.store import ConversationStore
from app.conversation.transcript import ELISION, Transcript
from app.llm import llm_provider


@pytest.fixture
def store(monkeypatch):
    db = Path(tempfile.mkdtemp(prefix="nlfc_conv_")) / "conv.db"
    s = ConversationStore(db)
    monkeypatch.setattr("app.conversation._store", s)
    return s


# ── Transcript ─────────────────────────────────────────────────────

def test_append_turn_records_pair():
    t = Transcript()
    t.append_turn("建一个箱子", '{"decision":"execute"}')
    assert [m["role"] for m in t.messages] == ["user", "assistant"]
    assert t.turn_count == 1


def test_half_turn_is_ignored():
    """只有提问没有回答不入库，否则重放时会出现悬空的 user 消息。"""
    t = Transcript()
    t.append_turn("问题", "")
    t.append_turn("", "回答")
    assert t.messages == []


def test_render_puts_history_between_system_and_current_turn():
    t = Transcript()
    t.append_turn("第一轮", "第一轮回答")
    rendered = t.render("SYSTEM", "本轮提问")
    assert [m["role"] for m in rendered] == ["system", "user", "assistant", "user"]
    assert rendered[0]["content"] == "SYSTEM"
    assert rendered[-1]["content"] == "本轮提问"


def test_render_without_history_is_just_system_and_user():
    assert Transcript().render("S", "U") == [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "U"},
    ]


def test_trim_keeps_first_turn_and_recent_turns():
    """最早那轮含原始需求，必须留；中间的从最旧开始丢。"""
    t = Transcript(budget_chars=2000)
    t.append_turn("原始需求：总长4500mm", "第一次回答")
    for i in range(40):
        t.append_turn(f"中间第{i}轮 " + "x" * 200, f"中间回答{i} " + "y" * 200)
    t.append_turn("最后一轮提问", "最后一轮回答")

    rendered = t.render("SYS", "现在这轮")
    body = "\n".join(m["content"] for m in rendered)
    assert "原始需求：总长4500mm" in body
    assert "最后一轮回答" in body
    assert ELISION in body
    assert len(rendered) < len(t.messages)


def test_trim_preserves_role_alternation():
    t = Transcript(budget_chars=1500)
    t.append_turn("首轮", "首答")
    for i in range(30):
        t.append_turn(f"u{i} " + "x" * 150, f"a{i} " + "y" * 150)

    roles = [m["role"] for m in t.render("SYS", "本轮")]
    assert roles[0] == "system"
    assert all(a != b for a, b in zip(roles[1:], roles[2:]))


def test_no_trim_when_within_budget():
    t = Transcript(budget_chars=100_000)
    t.append_turn("a", "b")
    t.append_turn("c", "d")
    assert len(t.render("S", "U")) == 6


# ── 持久化 ─────────────────────────────────────────────────────────

def test_store_roundtrip(store):
    store.append("s1", [{"role": "user", "content": "u"}, {"role": "assistant", "content": "a"}])
    assert store.load("s1").messages == [
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "a"},
    ]


def test_store_isolates_sessions(store):
    store.append("s1", [{"role": "user", "content": "s1-msg"}])
    store.append("s2", [{"role": "user", "content": "s2-msg"}])
    assert store.load("s1").messages[0]["content"] == "s1-msg"
    assert store.message_count("s2") == 1


def test_store_appends_preserve_order(store):
    for i in range(5):
        store.append("s1", [{"role": "user", "content": f"m{i}"}])
    assert [m["content"] for m in store.load("s1").messages] == ["m0", "m1", "m2", "m3", "m4"]


# ── 作用域 ─────────────────────────────────────────────────────────

def test_scope_persists_new_turns_only(store):
    with conversation_scope("s1") as t:
        t.append_turn("第一问", "第一答")
    with conversation_scope("s1") as t:
        assert t.turn_count == 1
        t.append_turn("第二问", "第二答")

    assert store.message_count("s1") == 4
    assert [m["content"] for m in store.load("s1").messages] == [
        "第一问", "第一答", "第二问", "第二答",
    ]


def test_no_active_transcript_outside_scope(store):
    assert active_transcript() is None
    with conversation_scope("s1"):
        assert active_transcript() is not None
    assert active_transcript() is None


def test_scope_disabled_yields_none(store):
    with conversation_scope("s1", enabled=False) as t:
        assert t is None
    with conversation_scope("") as t:
        assert t is None


def test_store_failure_does_not_break_the_loop(monkeypatch):
    """对话是增强项，存储挂了建模仍要能跑。"""
    class Broken:
        def load(self, _):
            raise RuntimeError("disk gone")

    monkeypatch.setattr("app.conversation._store", Broken())
    with conversation_scope("s1") as t:
        assert t is None


# ── 与 call_llm 的接线 ─────────────────────────────────────────────

def _stub_llm(monkeypatch, seen):
    monkeypatch.setattr(llm_provider, "_get_llm_config", lambda: ("k", "u", "m"))

    def fake(messages, **kwargs):
        seen.append(messages)
        return {"ok": True}, None, None, '{"ok": true}'

    monkeypatch.setattr(llm_provider, "_attempt_llm_call", fake)


def test_call_llm_sends_only_two_messages_outside_scope(store, monkeypatch):
    seen = []
    _stub_llm(monkeypatch, seen)
    llm_provider.call_llm("问题", "系统")
    assert [m["role"] for m in seen[0]] == ["system", "user"]


def test_call_llm_accumulates_across_calls_in_scope(store, monkeypatch):
    seen = []
    _stub_llm(monkeypatch, seen)
    with conversation_scope("s1"):
        llm_provider.call_llm("第一问", "系统")
        llm_provider.call_llm("第二问", "系统")

    assert [m["role"] for m in seen[0]] == ["system", "user"]
    # 第二次调用必须看得见第一次的问答
    assert [m["role"] for m in seen[1]] == ["system", "user", "assistant", "user"]
    assert seen[1][1]["content"] == "第一问"
    assert seen[1][2]["content"] == '{"ok": true}'


def test_history_survives_across_scopes(store, monkeypatch):
    """跨 HTTP 端点（next_step → evaluate_step）必须接得上。"""
    seen = []
    _stub_llm(monkeypatch, seen)
    with conversation_scope("s1"):
        llm_provider.call_llm("next_step 问题", "系统A")
    with conversation_scope("s1"):
        llm_provider.call_llm("evaluate 问题", "系统B")

    assert [m["role"] for m in seen[1]] == ["system", "user", "assistant", "user"]
    assert seen[1][0]["content"] == "系统B"
    assert seen[1][1]["content"] == "next_step 问题"


def test_transcript_note_replaces_bulky_user_message(store, monkeypatch):
    """历史里存精简说明，不存文档状态快照。"""
    seen = []
    _stub_llm(monkeypatch, seen)
    with conversation_scope("s1"):
        llm_provider.call_llm(
            "巨大的文档状态快照" * 500, "系统", transcript_note="执行结果 create_box → success"
        )
        llm_provider.call_llm("下一问", "系统")

    assert seen[1][1]["content"] == "执行结果 create_box → success"
    assert "巨大的文档状态快照" not in seen[1][1]["content"]


def test_record_false_reads_history_but_does_not_write(store, monkeypatch):
    seen = []
    _stub_llm(monkeypatch, seen)
    with conversation_scope("s1"):
        llm_provider.call_llm("主线问题", "系统")
        llm_provider.call_llm("旁路问题", "系统", record=False)
    assert [m["content"] for m in store.load("s1").messages] == ["主线问题", '{"ok": true}']


def test_failed_call_records_nothing(store, monkeypatch):
    monkeypatch.setattr(llm_provider, "_get_llm_config", lambda: ("k", "u", "m"))
    monkeypatch.setattr(llm_provider.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        llm_provider, "_attempt_llm_call",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with conversation_scope("s1"):
        assert llm_provider.call_llm("问题", "系统") is None
    assert store.message_count("s1") == 0


def test_execution_summary_is_compact_and_informative():
    note = llm_provider._summarize_execution_for_transcript(
        {"call_id": "P1_S1", "tool": "create_box", "args": {"name": "Body", "length": 100}},
        {"status": "success", "produced_objects": ["Body"]},
    )
    assert "P1_S1" in note and "create_box" in note
    assert "name=Body" in note and "Body" in note
    assert len(note) < 300


def test_execution_summary_surfaces_errors():
    note = llm_provider._summarize_execution_for_transcript(
        {"call_id": "P1_S2", "tool": "add_fillet", "args": {"target": "Missing"}},
        {"status": "error", "message": "Object not found"},
        {"passed": False, "issues": ["tool_execution_failed"]},
    )
    assert "error" in note
    assert "Object not found" in note
    assert "tool_execution_failed" in note
