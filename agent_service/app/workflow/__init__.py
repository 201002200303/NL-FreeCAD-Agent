"""Workflow spine.

- 对话主路径：`chat.chat_turn` / `chat.compress_context`（Cursor 式）
- 兼容旧三段式：`service.start_plan` / `next_step` / `evaluate_step`
"""
from app.workflow.service import (
    start_plan,
    next_step,
    evaluate_step,
    legacy_plan,
    plan_next_step_node,
    validate_next_step_node,
    evaluate_step_node,
    should_end,
)
from app.workflow.chat import chat_turn, compress_context

__all__ = [
    "chat_turn",
    "compress_context",
    "start_plan",
    "next_step",
    "evaluate_step",
    "legacy_plan",
    "plan_next_step_node",
    "validate_next_step_node",
    "evaluate_step_node",
    "should_end",
]
