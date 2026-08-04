"""Fallback: build a memory pack from raw execution_history when client has no SessionMemory."""

from __future__ import annotations

from typing import Any

RECENT_EVENTS_MAX = 5


def build_memory_pack_from_history(
    execution_history: dict | None,
    *,
    user_input: str = "",
    goal: str = "",
    name_map: dict | None = None,
    current_phase_id: str | None = None,
    current_abstract_step: dict | None = None,
) -> dict:
    history = execution_history or {}
    recent = list(history.get("recent") or [])[-RECENT_EVENTS_MAX:]
    object_memory: dict[str, dict] = {}
    query_cache: dict[str, dict] = {}
    error_memory: dict[str, Any] = {}
    recent_events: list[dict] = []
    completed: list[str] = []
    pending: list[str] = []
    current_target = None

    for entry in recent:
        tool = entry.get("tool", "")
        status = entry.get("status", "")
        target = entry.get("query_target") or _extract_target_from_entry(entry)
        if target:
            current_target = target
        if entry.get("kind") == "query" or tool in _QUERY_TOOLS:
            if status == "success":
                query_result = entry.get("query_result") or {}
                cache_target = target or query_result.get("name") or "__document__"
                from app.memory.geometry_facts import extract_spatial_facts, has_spatial_facts

                facts = extract_spatial_facts(query_result)
                query_cache[cache_target] = {
                    "tool": tool,
                    "call_id": entry.get("call_id"),
                    "summary": _summarize_query_result(query_result),
                    "query_result": query_result,
                    "has_spatial_facts": has_spatial_facts(query_result=query_result),
                    "size": facts.get("size"),
                    "center": facts.get("center"),
                }
        elif status == "success":
            for name in entry.get("produced_objects") or []:
                object_memory[name] = {
                    "type": "unknown",
                    "role": "part",
                    "status": "created",
                    "last_known": "success",
                }
        elif status in {"error", "failed"}:
            error_memory["last_error"] = {
                "tool": tool,
                "args": entry.get("args") or {},
                "message": entry.get("message") or "unknown error",
                "avoid_repeating": True,
            }
            pending.append(f"失败: {tool} — {entry.get('message', '')}")

        recent_events.append({
            "call_id": entry.get("call_id"),
            "tool": tool,
            "status": status,
            "target": target,
            "message": entry.get("message"),
            "kind": entry.get("kind") or ("query" if tool in _QUERY_TOOLS else "act"),
        })

    if name_map:
        for old_name, new_name in name_map.items():
            if old_name in object_memory and new_name not in object_memory:
                object_memory[new_name] = {**object_memory.pop(old_name), "renamed_from": old_name}

    working_lines = [f"目标: {goal or user_input}"]
    if current_phase_id:
        working_lines.append(f"当前进度: {current_phase_id}")
    if current_abstract_step:
        working_lines.append(
            f"当前步骤: {current_abstract_step.get('step_id', '')} "
            f"{current_abstract_step.get('title') or current_abstract_step.get('intent', '')}"
        )
    if error_memory.get("last_error"):
        err = error_memory["last_error"]
        working_lines.append(f"最近错误: {err.get('tool')} — {err.get('message')}；不要原样重试")

    long_parts = []
    if completed:
        long_parts.append("已完成:\n" + "\n".join(f"- {line}" for line in completed))
    if pending:
        long_parts.append("失败/待处理:\n" + "\n".join(f"- {line}" for line in pending[-5:]))

    # Fallback phase window: filter by phase_id when history is tagged.
    phase_id = (current_abstract_step or {}).get("step_id") or current_phase_id
    tagged = [e for e in recent_events if e.get("phase_id")]
    if tagged and phase_id:
        phase_events = [e for e in recent_events if e.get("phase_id") == phase_id]
    else:
        phase_events = list(recent_events)

    return {
        "working_summary": "\n".join(working_lines),
        "recent_events": recent_events[-RECENT_EVENTS_MAX:],
        "phase_events": phase_events[-40:],
        "phase_conclusions": [],
        "object_memory": object_memory,
        "error_memory": error_memory,
        "query_cache": {
            k: {
                kk: vv
                for kk, vv in v.items()
                if kk != "query_result"
            }
            for k, v in query_cache.items()
        },
        "progress": {
            "current_phase_id": phase_id,
            "current_step_id": (current_abstract_step or {}).get("step_id"),
        },
        "long_summary": "\n\n".join(long_parts),
        "current_target": current_target,
        "_query_cache_full": query_cache,
    }


_QUERY_TOOLS = {
    "summarize_document",
    "get_object_detail",
    "measure_gap",
    "compare_orientation",
    "list_topology",
}


def _extract_target_from_entry(entry: dict) -> str | None:
    for field in ("target", "query_target", "base", "tool", "obj_a", "obj_b"):
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _summarize_query_result(query_result: dict | None) -> str:
    from app.memory.geometry_facts import summarize_query_result

    return summarize_query_result(query_result)
