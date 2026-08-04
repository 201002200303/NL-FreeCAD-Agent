"""Format SessionMemory pack for LLM prompts."""

from __future__ import annotations

import json
from typing import Any, Optional

from app.schemas.cad_state import DocumentState


def resolve_memory_pack(
    session_memory: dict | None,
    execution_history: dict | None,
    *,
    user_input: str = "",
    goal: str = "",
    name_map: dict | None = None,
    current_phase_id: str | None = None,
    current_abstract_step: dict | None = None,
) -> dict:
    if session_memory:
        return session_memory
    from app.memory.pack_builder import build_memory_pack_from_history

    return build_memory_pack_from_history(
        execution_history,
        user_input=user_input,
        goal=goal,
        name_map=name_map,
        current_phase_id=current_phase_id,
        current_abstract_step=current_abstract_step,
    )


def _format_event_lines(events: list[dict]) -> list[str]:
    lines = []
    for entry in events:
        tool = entry.get("tool", "")
        status = entry.get("status", "")
        target = entry.get("target")
        msg = entry.get("message")
        line = f"- {entry.get('call_id', '')} {tool}"
        if target:
            line += f" target={target}"
        line += f": {status}"
        if msg:
            line += f" — {msg}"
        produced = entry.get("produced_objects") or []
        if produced:
            line += f" → {', '.join(produced)}"
        lines.append(line)
    return lines


def format_memory_for_prompt(memory_pack: dict, name_map: dict | None = None) -> str:
    sections: list[str] = []

    working = memory_pack.get("working_summary")
    if working:
        sections.append(f"## 工作记忆\n{working}")

    conclusions = memory_pack.get("phase_conclusions") or []
    if conclusions:
        lines = []
        for item in conclusions:
            if isinstance(item, dict):
                produced = item.get("produced") or []
                extra = f" → {', '.join(produced)}" if produced else ""
                lines.append(f"- {item.get('summary') or item.get('phase_id', '?')}{extra}")
            else:
                lines.append(f"- {item}")
        sections.append("## 已完成阶段结论\n" + "\n".join(lines))
    else:
        long_summary = memory_pack.get("long_summary")
        if long_summary:
            sections.append(f"## 长期摘要\n{long_summary}")

    progress = memory_pack.get("progress") or {}
    if progress:
        sections.append(
            "## 计划进度\n"
            f"```json\n{json.dumps(progress, ensure_ascii=False, indent=2)}\n```"
        )

    phase_events = memory_pack.get("phase_events") or []
    if phase_events:
        sections.append("## 当前阶段轨迹\n" + "\n".join(_format_event_lines(phase_events)))
    else:
        recent_events = memory_pack.get("recent_events") or []
        if recent_events:
            sections.append("## 最近关键事件\n" + "\n".join(_format_event_lines(recent_events)))

    object_memory = memory_pack.get("object_memory") or {}
    if object_memory:
        sections.append(
            "## 对象索引\n"
            f"```json\n{json.dumps(object_memory, ensure_ascii=False, indent=2)}\n```"
        )

    query_cache = memory_pack.get("query_cache") or {}
    if query_cache:
        sections.append(
            "## 查询缓存\n"
            "规则：仅当某 target 的缓存含 `size`+`center`（或 `has_spatial_facts=true`）时，"
            "才算已覆盖，不要重复 query；若摘要含 `spatial_facts=incomplete` 或缺少 size/center，"
            "允许再查一次能拿到 bbox 的工具，然后必须 act。\n"
            f"```json\n{json.dumps(query_cache, ensure_ascii=False, indent=2)}\n```"
        )

    error_memory = memory_pack.get("error_memory") or {}
    last_error = error_memory.get("last_error")
    if last_error:
        sections.append(
            "## 错误记忆（必须遵守）\n"
            f"```json\n{json.dumps(last_error, ensure_ascii=False, indent=2)}\n```\n"
            "下一轮不要原样重试上述失败调用；先修复根因、换工具或降级方案。"
        )

    if name_map:
        lines = [f"- {old} → {new}" for old, new in name_map.items()]
        sections.append("## 对象名称映射\n" + "\n".join(lines))

    return "\n\n".join(sections)


def build_compact_document_context(
    document_state: Optional[DocumentState],
    memory_pack: dict | None = None,
) -> str:
    """Prefer object_memory index; fall back to full document_state."""
    object_memory = (memory_pack or {}).get("object_memory") or {}
    current_target = (memory_pack or {}).get("current_target")
    query_cache = (memory_pack or {}).get("query_cache") or {}

    if object_memory:
        lines = ["## 当前文档对象索引（紧凑）\n"]
        if document_state:
            lines.append(f"文档名称: {document_state.document_name}")
        lines.append(f"共 {len(object_memory)} 个已跟踪对象:")
        for name, info in object_memory.items():
            parts = [f"`{name}` type={info.get('type', '?')}"]
            if info.get("role"):
                parts.append(f"role={info['role']}")
            if info.get("status"):
                parts.append(f"status={info['status']}")
            if info.get("last_known"):
                parts.append(f"last={info['last_known']}")
            if info.get("size"):
                parts.append(f"size={info['size']}")
            if info.get("center"):
                parts.append(f"center={info['center']}")
            if info.get("last_error"):
                parts.append(f"err={info['last_error']}")
            lines.append("- " + ", ".join(parts))

        if current_target and current_target in query_cache:
            lines.append(f"\n当前 target `{current_target}` 已有查询: {query_cache[current_target].get('summary', '')}")

        if document_state and document_state.objects:
            untracked = [
                obj.name for obj in document_state.objects
                if obj.name not in object_memory
            ]
            if untracked:
                lines.append("\n未索引对象（仅名称）: " + ", ".join(untracked[:20]))
        return "\n".join(lines)

    from app.llm.llm_provider import _build_document_context

    return _build_document_context(document_state)
