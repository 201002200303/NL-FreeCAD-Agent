# session_memory.py — 四层工作记忆：working / object / error / long summary

from __future__ import annotations

from typing import Any

RECENT_EVENTS_MAX = 5
COMPLETED_SUMMARY_MAX = 12

TARGET_FIELDS = (
    "target",
    "base",
    "tool",
    "obj_a",
    "obj_b",
    "part1",
    "part2",
    "name",
)


def _extract_target(tool_call: dict) -> str | None:
    args = tool_call.get("args") or {}
    for field in TARGET_FIELDS:
        value = args.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _summarize_query_result(query_result: dict | None) -> str:
    if not query_result:
        return ""
    if query_result.get("summary"):
        return str(query_result["summary"])
    parts: list[str] = []
    name = query_result.get("name")
    if name:
        parts.append(f"name={name}")
    obj_type = query_result.get("type")
    if obj_type:
        parts.append(f"type={obj_type}")
    bbox = query_result.get("bbox") or {}
    size = bbox.get("size")
    if size:
        parts.append(f"size={size}")
    center = bbox.get("center")
    if center:
        parts.append(f"center={center}")
    placement = query_result.get("placement") or {}
    base = placement.get("base")
    if base:
        parts.append(f"pos={base}")
    message = query_result.get("message")
    if message:
        parts.append(str(message))
    gap = query_result.get("gap")
    if gap is not None:
        parts.append(f"gap={gap}")
    orientation = query_result.get("orientation") or query_result.get("axis")
    if orientation:
        parts.append(f"orientation={orientation}")
    objects = query_result.get("objects") or []
    if objects:
        names = [obj.get("name") for obj in objects if isinstance(obj, dict) and obj.get("name")]
        if names:
            parts.append(f"objects={', '.join(names[:8])}")
    return "; ".join(parts) or "query ok"


def _infer_role(name: str, tool_call: dict | None = None) -> str:
    lowered = name.lower()
    hints = {
        "chassis": ("chassis", "base", "body", "frame"),
        "wheel": ("wheel", "tire"),
        "hood": ("hood", "bonnet"),
        "cabin": ("cabin", "cab"),
        "sketch": ("sketch", "profile"),
        "hole": ("hole", "cut"),
        "fillet": ("fillet", "chamfer"),
    }
    for role, tokens in hints.items():
        if any(token in lowered for token in tokens):
            return role
    if tool_call:
        tool = tool_call.get("tool", "")
        if tool in {"create_sketch", "create_sketch_on_face"}:
            return "sketch"
        if tool in {"create_box", "create_cylinder"}:
            return "primitive"
    return "part"


def _event_key(entry: dict) -> str:
    tool = entry.get("tool", "")
    target = entry.get("target") or entry.get("query_target") or ""
    status = entry.get("status", "")
    return f"{tool}:{target}:{status}"


class SessionMemory:
    """Compress execution history into agent-usable working memory."""

    def __init__(self, goal: str = "", user_input: str = ""):
        self.goal = goal or user_input
        self.user_input = user_input
        self.object_memory: dict[str, dict] = {}
        self.query_cache: dict[str, dict] = {}
        self.error_memory: dict[str, Any] = {}
        self.recent_events: list[dict] = []
        self.completed_summaries: list[str] = []
        self.pending_summaries: list[str] = []
        self.progress: dict[str, Any] = {}
        self.current_target: str | None = None
        self._seen_event_keys: set[str] = set()

    def set_goal(self, goal: str, user_input: str = ""):
        self.goal = goal or user_input
        if user_input:
            self.user_input = user_input

    def sync_from_document(self, document_state: dict | None):
        if not document_state:
            return
        for obj in document_state.get("objects") or []:
            if not isinstance(obj, dict):
                continue
            name = obj.get("name")
            if not name:
                continue
            entry = self.object_memory.setdefault(name, {})
            entry["type"] = obj.get("type", entry.get("type", "unknown"))
            entry.setdefault("role", _infer_role(name))
            bbox = obj.get("bbox") or {}
            if bbox.get("size"):
                entry["size"] = bbox.get("size")
            if bbox.get("center"):
                entry["center"] = bbox.get("center")
            entry.setdefault("status", "present")

    def update_progress(
        self,
        *,
        current_phase_id: str | None = None,
        current_abstract_step: dict | None = None,
        abstract_step_queue: dict | None = None,
        high_level_plan: dict | None = None,
        evaluate_message: str | None = None,
    ):
        progress = dict(self.progress)
        if current_phase_id:
            progress["current_phase_id"] = current_phase_id
        if current_abstract_step:
            progress["current_step_id"] = current_abstract_step.get("step_id")
            progress["current_step_title"] = current_abstract_step.get("title") or current_abstract_step.get("intent")
        if abstract_step_queue:
            steps = abstract_step_queue.get("steps") or []
            completed = [s for s in steps if s.get("status") == "completed"]
            pending = [s for s in steps if s.get("status") != "completed"]
            progress["completed_steps"] = [s.get("step_id") for s in completed if s.get("step_id")]
            progress["pending_steps"] = [s.get("step_id") for s in pending if s.get("step_id")]
        if high_level_plan:
            phases = high_level_plan.get("phases") or []
            progress["goal"] = high_level_plan.get("goal") or self.goal
            progress["phase_overview"] = [
                {
                    "phase_id": p.get("phase_id"),
                    "title": p.get("title"),
                    "intent": p.get("intent"),
                }
                for p in phases
                if isinstance(p, dict)
            ]
        if evaluate_message:
            progress["last_evaluate_message"] = evaluate_message
        self.progress = progress
        self._rebuild_phase_summaries(high_level_plan, abstract_step_queue, evaluate_message)

    def update_from_tool(
        self,
        tool_call: dict,
        exec_result: dict,
        *,
        phase_id: str | None = None,
        name_map: dict | None = None,
    ):
        tool_name = tool_call.get("tool", exec_result.get("tool", ""))
        call_id = tool_call.get("call_id", exec_result.get("call_id", ""))
        status = exec_result.get("status", "unknown")
        target = (
            exec_result.get("query_target")
            or _extract_target(tool_call)
        )
        if target:
            self.current_target = target

        for old_name, new_name in (name_map or {}).items():
            if old_name in self.object_memory:
                self.object_memory[new_name] = {
                    **self.object_memory.pop(old_name),
                    "renamed_from": old_name,
                }
            self.query_cache.pop(old_name, None)
            if target == old_name:
                target = new_name
                self.current_target = new_name

        if exec_result.get("kind") == "query" or tool_name in {
            "summarize_document",
            "get_object_detail",
            "measure_gap",
            "compare_orientation",
            "list_topology",
        }:
            self._update_query_cache(tool_name, call_id, phase_id, exec_result, target)
        elif status == "success":
            self._update_objects_from_success(tool_call, exec_result, phase_id)
            self.error_memory.pop("last_error", None)
        else:
            self._update_error_memory(tool_call, exec_result, phase_id)

        self._push_recent_event({
            "call_id": call_id,
            "tool": tool_name,
            "status": status,
            "target": target,
            "phase_id": phase_id,
            "message": exec_result.get("message"),
            "kind": exec_result.get("kind") or ("query" if tool_name.startswith("get_") else "act"),
            "produced_objects": exec_result.get("produced_objects") or [],
        })

    def update_from_evaluate(self, evaluate_result: dict, high_level_plan: dict | None = None):
        message = evaluate_result.get("message")
        phase_status = evaluate_result.get("phase_status")
        phase_id = evaluate_result.get("updated_current_phase_id") or evaluate_result.get("phase_id")
        if phase_status == "completed" and message:
            summary = f"{phase_id or '当前阶段'}: {message}"
            if summary not in self.completed_summaries:
                self.completed_summaries.append(summary)
                self.completed_summaries = self.completed_summaries[-COMPLETED_SUMMARY_MAX:]
        if evaluate_result.get("decision") == "repair" and message:
            self.pending_summaries = [line for line in self.pending_summaries if message not in line]
            self.pending_summaries.append(f"待修复: {message}")
            self.pending_summaries = self.pending_summaries[-5:]
        self.update_progress(
            current_phase_id=phase_id,
            current_abstract_step=evaluate_result.get("current_abstract_step"),
            abstract_step_queue=evaluate_result.get("abstract_step_queue"),
            high_level_plan=high_level_plan,
            evaluate_message=message,
        )

    def build_pack(self) -> dict:
        return {
            "working_summary": self._build_working_summary(),
            "recent_events": list(self.recent_events[-RECENT_EVENTS_MAX:]),
            "object_memory": dict(self.object_memory),
            "error_memory": dict(self.error_memory),
            "query_cache": self._compact_query_cache(),
            "progress": dict(self.progress),
            "long_summary": self._build_long_summary(),
            "current_target": self.current_target,
        }

    def _update_query_cache(
        self,
        tool_name: str,
        call_id: str,
        phase_id: str | None,
        exec_result: dict,
        target: str | None,
    ):
        if exec_result.get("status") != "success":
            return
        query_result = exec_result.get("query_result") or {}
        targets = []
        if target:
            targets.append(target)
        query_targets = exec_result.get("query_targets") or []
        targets.extend([t for t in query_targets if isinstance(t, str)])
        if query_result.get("name"):
            targets.append(query_result["name"])
        for obj in query_result.get("objects") or []:
            if isinstance(obj, dict) and obj.get("name"):
                targets.append(obj["name"])
        if not targets and tool_name == "summarize_document":
            targets.append("__document__")

        summary = _summarize_query_result(query_result)
        for tgt in dict.fromkeys(targets):
            self.query_cache[tgt] = {
                "tool": tool_name,
                "call_id": call_id,
                "step_id": phase_id,
                "summary": summary,
                "query_result": query_result,
            }

    def _update_objects_from_success(self, tool_call: dict, exec_result: dict, phase_id: str | None):
        produced = list(exec_result.get("produced_objects") or [])
        target = _extract_target(tool_call)
        if target and target not in produced:
            produced.append(target)
        for name in produced:
            role = _infer_role(name, tool_call)
            entry = self.object_memory.setdefault(name, {})
            expected = (tool_call.get("expected_effect") or {})
            entry.update({
                "type": expected.get("type") or entry.get("type", "unknown"),
                "role": role,
                "status": "created" if tool_call.get("tool", "").startswith("create_") else "modified",
                "last_known": "success",
                "last_step": phase_id or entry.get("last_step"),
            })

    def _update_error_memory(self, tool_call: dict, exec_result: dict, phase_id: str | None):
        message = exec_result.get("message") or "unknown error"
        likely_cause = exec_result.get("likely_cause")
        if not likely_cause:
            lowered = message.lower()
            if "empty shape" in lowered:
                likely_cause = "profile sketch has no closed geometry"
            elif "not found" in lowered or "不存在" in message:
                likely_cause = "target object missing or renamed"
            elif "invalid" in lowered:
                likely_cause = "invalid args or topology selection"
        self.error_memory["last_error"] = {
            "tool": tool_call.get("tool"),
            "args": tool_call.get("args") or {},
            "call_id": tool_call.get("call_id"),
            "phase_id": phase_id,
            "message": message,
            "likely_cause": likely_cause,
            "avoid_repeating": True,
        }
        self.pending_summaries = [
            line for line in self.pending_summaries
            if message not in line
        ]
        self.pending_summaries.append(f"失败: {tool_call.get('tool')} — {message}")
        self.pending_summaries = self.pending_summaries[-5:]

        target = _extract_target(tool_call)
        if target and target in self.object_memory:
            self.object_memory[target]["last_known"] = "error"
            self.object_memory[target]["last_error"] = message

    def _push_recent_event(self, entry: dict):
        key = _event_key(entry)
        if key in self._seen_event_keys and entry.get("kind") == "query":
            return
        self._seen_event_keys.add(key)
        self.recent_events.append(entry)
        self.recent_events = self.recent_events[-RECENT_EVENTS_MAX:]

    def _compact_query_cache(self) -> dict:
        compact = {}
        for target, item in self.query_cache.items():
            compact[target] = {
                "tool": item.get("tool"),
                "call_id": item.get("call_id"),
                "step_id": item.get("step_id"),
                "summary": item.get("summary"),
            }
        return compact

    def _build_working_summary(self) -> str:
        lines = [f"目标: {self.goal or self.user_input}"]
        progress = self.progress or {}
        step_title = progress.get("current_step_title")
        phase_id = progress.get("current_phase_id")
        if phase_id or step_title:
            lines.append(f"当前进度: {phase_id or ''} {step_title or ''}".strip())
        if self.current_target:
            lines.append(f"当前关注对象: {self.current_target}")
        last_error = self.error_memory.get("last_error")
        if last_error:
            lines.append(
                "最近错误: "
                f"{last_error.get('tool')} — {last_error.get('message')}；"
                f"不要原样重试，先修复根因（{last_error.get('likely_cause') or '见 message'}）"
            )
        if self.query_cache and self.current_target and self.current_target in self.query_cache:
            lines.append(f"已有查询: {self.query_cache[self.current_target].get('summary', '')}")
        return "\n".join(lines)

    def _build_long_summary(self) -> str:
        completed = self.completed_summaries[-8:]
        pending = self.pending_summaries[-5:]
        parts = []
        if completed:
            parts.append("已完成:\n" + "\n".join(f"- {line}" for line in completed))
        if pending:
            parts.append("失败/待处理:\n" + "\n".join(f"- {line}" for line in pending))
        return "\n\n".join(parts)

    def _rebuild_phase_summaries(
        self,
        high_level_plan: dict | None,
        abstract_step_queue: dict | None,
        evaluate_message: str | None,
    ):
        if not high_level_plan:
            return
        phases = high_level_plan.get("phases") or []
        current_phase_id = (self.progress or {}).get("current_phase_id")
        for phase in phases:
            pid = phase.get("phase_id")
            if not pid or not current_phase_id:
                continue
            try:
                current_idx = next(i for i, p in enumerate(phases) if p.get("phase_id") == current_phase_id)
                phase_idx = next(i for i, p in enumerate(phases) if p.get("phase_id") == pid)
            except StopIteration:
                continue
            if phase_idx >= current_idx:
                continue
            summary = f"{pid}: {phase.get('title') or phase.get('intent', '')}"
            if summary not in self.completed_summaries:
                self.completed_summaries.append(summary)
        if evaluate_message and abstract_step_queue:
            steps = abstract_step_queue.get("steps") or []
            completed_steps = [s for s in steps if s.get("status") == "completed"]
            for step in completed_steps[-3:]:
                line = f"{step.get('step_id')}: {step.get('title') or step.get('intent', '完成')}"
                if line not in self.completed_summaries:
                    self.completed_summaries.append(line)
        self.completed_summaries = self.completed_summaries[-COMPLETED_SUMMARY_MAX:]
