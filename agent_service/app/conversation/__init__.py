"""对话层：一个 session 内跨 HTTP 端点累积的消息流。

用法（在 HTTP 端点包住工作流调用，与 trace 同层）：

    with conversation_scope(session_id):
        result = workflow.next_step(...)

作用域内的 `call_llm` 会自动带上历史回合，并把本轮记进去；作用域退出时落库。
用 contextvar 而不是逐层传参，与 `app.debug.trace_logger` 保持同一种写法。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

from app.conversation.store import ConversationStore
from app.conversation.transcript import Transcript

_active: ContextVar[Optional[Transcript]] = ContextVar("conversation_transcript", default=None)
_store: Optional[ConversationStore] = None


def get_store() -> ConversationStore:
    global _store
    if _store is None:
        _store = ConversationStore()
    return _store


def active_transcript() -> Optional[Transcript]:
    """当前作用域的消息流；不在作用域内返回 None（此时 LLM 调用维持无历史）。"""
    return _active.get()


@contextmanager
def conversation_scope(session_id: str, *, enabled: bool = True) -> Iterator[Optional[Transcript]]:
    """载入 session 的历史，作用域内累积，退出时把新增部分落库。"""
    if not enabled or not session_id:
        yield None
        return

    try:
        transcript = get_store().load(session_id)
    except Exception as exc:  # 对话是增强项，存储故障不该拖垮建模主流程
        print(f"[conversation] load failed ({session_id}): {exc}")
        yield None
        return

    baseline = len(transcript.messages)
    token = _active.set(transcript)
    try:
        yield transcript
    finally:
        _active.reset(token)
        appended = transcript.messages[baseline:]
        if appended:
            try:
                get_store().append(session_id, appended)
            except Exception as exc:
                print(f"[conversation] append failed ({session_id}): {exc}")


__all__ = [
    "ConversationStore",
    "Transcript",
    "active_transcript",
    "conversation_scope",
    "get_store",
]
