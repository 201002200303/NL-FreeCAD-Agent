"""跨轮累积的对话记录（chat transcript）。

一个 session 内的多次 `/agent/chat` 共享一条持续增长的消息流，避免每轮冷启动。

**记什么**：助手输出摘要 + 精简回合说明。
**不记什么**：完整文档状态快照（由每轮 pending user 临时注入，不进历史）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# 用户明确接受更高的 token 成本，预算给得比较宽；超出后从最旧的回合开始丢。
DEFAULT_BUDGET_CHARS = 120_000
ELISION = "…（此处省略较早的若干回合，最初的需求与最近的进展已保留）"


def _merge_adjacent(messages: list[dict]) -> list[dict]:
    """合并相邻同角色消息，保证 user/assistant 严格交替。

    旁白（`append_note`）与修剪省略标记都会产生相邻同角色消息，部分
    OpenAI 兼容后端对此并不宽容。
    """
    merged: list[dict] = []
    for msg in messages:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1] = {
                "role": msg["role"],
                "content": f"{merged[-1]['content']}\n\n{msg['content']}",
            }
        else:
            merged.append(dict(msg))
    return merged


def _budget_from_env() -> int:
    raw = os.getenv("CONVERSATION_BUDGET_CHARS", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_BUDGET_CHARS


@dataclass
class Transcript:
    """一个 session 的消息流。只存 user/assistant，system 每次由调用方给。"""

    messages: list[dict] = field(default_factory=list)
    budget_chars: int = field(default_factory=_budget_from_env)

    def append_turn(self, user_content: str, assistant_content: str) -> None:
        """记一个完整回合。半个回合（只有提问没有回答）不入库，避免污染重放。"""
        user_content = (user_content or "").strip()
        assistant_content = (assistant_content or "").strip()
        if not user_content or not assistant_content:
            return
        self.messages.append({"role": "user", "content": user_content})
        self.messages.append({"role": "assistant", "content": assistant_content})

    def append_note(self, content: str) -> None:
        """记一条没有模型回答的旁白，例如「暂停期间用户手工删了 Body」。

        这类事实必须让模型看见，否则它会带着过时记忆继续推进。单边消息由
        `render` 合并进下一条 user 消息，不会打断角色交替。
        """
        content = (content or "").strip()
        if content:
            self.messages.append({"role": "user", "content": content})

    def render(self, system_prompt: str, pending_user: str) -> list[dict]:
        """拼成本次调用的完整消息数组：system + 历史回合 + 本轮提问。"""
        history = self._trim(reserve=len(system_prompt) + len(pending_user or ""))
        return _merge_adjacent(
            [
                {"role": "system", "content": system_prompt},
                *history,
                {"role": "user", "content": pending_user},
            ]
        )

    def _trim(self, *, reserve: int = 0) -> list[dict]:
        """预算内保留尽量多的近期回合；最早那个回合始终保留（含原始需求）。"""
        allowance = max(self.budget_chars - reserve, 0)
        total = sum(len(m["content"]) for m in self.messages)
        if total <= allowance:
            return list(self.messages)

        head = self.messages[:2]
        used = sum(len(m["content"]) for m in head) + len(ELISION)

        tail: list[dict] = []
        # 成对回退，保证 user/assistant 配对不被拆散
        for i in range(len(self.messages) - 2, 1, -2):
            turn = self.messages[i : i + 2]
            turn_len = sum(len(m["content"]) for m in turn)
            if used + turn_len > allowance:
                break
            tail[:0] = turn
            used += turn_len

        if len(head) + len(tail) >= len(self.messages):
            return list(self.messages)
        # 省略标记若与相邻消息同角色，由 render 的 _merge_adjacent 合并
        return [*head, {"role": "user", "content": ELISION}, *tail]

    @property
    def turn_count(self) -> int:
        return len(self.messages) // 2

    @property
    def total_chars(self) -> int:
        return sum(len(m["content"]) for m in self.messages)
