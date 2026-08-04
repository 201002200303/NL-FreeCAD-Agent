"""Build LLM-facing context from durable runtime + session memory."""

from __future__ import annotations

import json
from typing import Optional

from app.memory.prompt import format_memory_for_prompt, resolve_memory_pack
from app.runtime.service import get_runtime


def build_llm_context(
    *,
    session_id: str | None,
    user_input: str = "",
    goal: str = "",
    document_state=None,
    session_memory: dict | None = None,
    execution_history: dict | None = None,
    name_map: dict | None = None,
    current_phase_id: str | None = None,
    current_abstract_step: dict | None = None,
) -> str:
    """Compose the dynamic LLM context block used by next_step / evaluate."""
    memory_pack = resolve_memory_pack(
        session_memory,
        execution_history,
        user_input=user_input,
        goal=goal,
        name_map=name_map,
        current_phase_id=current_phase_id,
        current_abstract_step=current_abstract_step,
    )

    sections = [format_memory_for_prompt(memory_pack, name_map=name_map)]

    if session_id:
        doc_dict = None
        if document_state is not None:
            if hasattr(document_state, "model_dump"):
                doc_dict = document_state.model_dump(mode="json")
            elif isinstance(document_state, dict):
                doc_dict = document_state
        try:
            slice_ = get_runtime().build_context_slice(
                session_id,
                document_state=doc_dict,
                session_memory=memory_pack,
                current_phase_id=current_phase_id,
                current_abstract_step=current_abstract_step,
            )
            sections.append(_format_runtime_slice(slice_))
        except Exception as exc:
            sections.append(f"## Runtime State\n(unavailable: {exc})")

    return "\n\n".join(section for section in sections if section)


def _format_runtime_slice(slice_: dict) -> str:
    lines = ["## Runtime State（可恢复）"]
    if slice_.get("status"):
        lines.append(f"- session_status: {slice_['status']}")
    if slice_.get("checkpoint_id"):
        lines.append(f"- checkpoint: `{slice_['checkpoint_id']}`")
    if slice_.get("current_phase_id"):
        lines.append(f"- current_phase: {slice_['current_phase_id']}")
    step = slice_.get("current_step") or {}
    if step:
        lines.append(
            f"- current_step: {step.get('step_id', '')} "
            f"{step.get('title') or step.get('intent') or ''}".strip()
        )

    related = slice_.get("related_cad_objects") or []
    if related:
        lines.append("\n### 与当前步骤相关的 CAD 对象")
        lines.append(f"```json\n{json.dumps(related, ensure_ascii=False, indent=2)}\n```")

    recent = slice_.get("recent_events") or []
    if recent:
        lines.append("\n### 最近事件（event log）")
        for event in recent[-8:]:
            payload = event.get("payload") or {}
            summary = payload.get("message") or payload.get("tool") or payload.get("decision") or ""
            tools = payload.get("tools")
            if tools:
                summary = f"tools={tools}"
            lines.append(
                f"- #{event.get('seq')} {event.get('type')} "
                f"{event.get('phase_id') or ''} {summary}".strip()
            )

    errors = slice_.get("unresolved_errors") or []
    if errors:
        lines.append("\n### 未解决错误")
        lines.append(f"```json\n{json.dumps(errors, ensure_ascii=False, indent=2)}\n```")

    user_changes = slice_.get("user_document_changes") or []
    if user_changes:
        lines.append("\n### 用户在暂停期间手工修改了文档（必须纳入决策）")
        for change in user_changes:
            lines.append(f"- {change.get('summary') or change}")

    completed = slice_.get("completed_stage_summaries") or []
    if completed:
        lines.append("\n### 已完成阶段摘要")
        lines.append(f"```json\n{json.dumps(completed, ensure_ascii=False, indent=2)}\n```")

    return "\n".join(lines)
