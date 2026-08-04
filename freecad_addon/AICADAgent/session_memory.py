# session_memory.py — 四层工作记忆：working / object / error / long summary

from __future__ import annotations

from typing import Any

RECENT_EVENTS_MAX = 5
CURRENT_PHASE_EVENTS_MAX = 40
PHASE_CONCLUSIONS_MAX = 12
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


def _normalize_bbox(bbox: Any) -> dict | None:
    if not isinstance(bbox, dict) or not bbox:
        return None
    if bbox.get("size") and bbox.get("center"):
        return {
            "size": list(bbox["size"]),
            "center": list(bbox["center"]),
            "xmin": bbox.get("xmin"),
            "xmax": bbox.get("xmax"),
            "ymin": bbox.get("ymin"),
            "ymax": bbox.get("ymax"),
            "zmin": bbox.get("zmin"),
            "zmax": bbox.get("zmax"),
        }
    if all(k in bbox for k in ("x", "y", "z")):
        try:
            xmin, xmax = float(bbox["x"][0]), float(bbox["x"][1])
            ymin, ymax = float(bbox["y"][0]), float(bbox["y"][1])
            zmin, zmax = float(bbox["z"][0]), float(bbox["z"][1])
        except (TypeError, ValueError, IndexError, KeyError):
            return None
        return {
            "xmin": xmin,
            "xmax": xmax,
            "ymin": ymin,
            "ymax": ymax,
            "zmin": zmin,
            "zmax": zmax,
            "size": [xmax - xmin, ymax - ymin, zmax - zmin],
            "center": [(xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2],
        }
    keys = ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")
    if all(k in bbox for k in keys):
        try:
            xmin, xmax = float(bbox["xmin"]), float(bbox["xmax"])
            ymin, ymax = float(bbox["ymin"]), float(bbox["ymax"])
            zmin, zmax = float(bbox["zmin"]), float(bbox["zmax"])
        except (TypeError, ValueError):
            return None
        return {
            "xmin": xmin,
            "xmax": xmax,
            "ymin": ymin,
            "ymax": ymax,
            "zmin": zmin,
            "zmax": zmax,
            "size": [xmax - xmin, ymax - ymin, zmax - zmin],
            "center": [(xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2],
        }
    return None


def _extract_spatial_facts(query_result: dict | None) -> dict:
    if not isinstance(query_result, dict):
        return {}
    facts: dict[str, Any] = {}
    bbox = _normalize_bbox(query_result.get("bbox"))
    if bbox:
        facts["bbox"] = bbox
        facts["size"] = bbox["size"]
        facts["center"] = bbox["center"]
    for obj in query_result.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        nested = _normalize_bbox(obj.get("bbox"))
        if nested:
            facts.setdefault("bbox", nested)
            facts.setdefault("size", nested["size"])
            facts.setdefault("center", nested["center"])
            break
        if obj.get("size") and obj.get("center"):
            facts.setdefault("size", obj["size"])
            facts.setdefault("center", obj["center"])
            break
    topo = query_result.get("topology") or {}
    if isinstance(topo, dict) and topo.get("volume") is not None:
        facts["volume"] = topo.get("volume")
    return facts


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
    facts = _extract_spatial_facts(query_result)
    if facts.get("size"):
        parts.append(f"size={facts['size']}")
    if facts.get("center"):
        parts.append(f"center={facts['center']}")
    if facts.get("volume") is not None:
        parts.append(f"volume={facts['volume']}")
    placement = query_result.get("placement") or {}
    base = placement.get("base")
    if base:
        parts.append(f"pos={base}")
    if query_result.get("face_count") is not None:
        parts.append(f"faces={query_result['face_count']}")
    if query_result.get("edge_count") is not None:
        parts.append(f"edges={query_result['edge_count']}")
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
    if not facts.get("size"):
        parts.append("spatial_facts=incomplete")
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
        self.phase_events: list[dict] = []
        self.phase_conclusions: list[dict] = []
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
        prev_phase = progress.get("current_phase_id")
        # Prefer abstract-step id when both are present (keeps phase window coherent).
        step_id = None
        if current_abstract_step:
            step_id = current_abstract_step.get("step_id")
            progress["current_step_id"] = step_id
            progress["current_step_title"] = (
                current_abstract_step.get("title") or current_abstract_step.get("intent")
            )
        next_phase = step_id or current_phase_id
        if next_phase and prev_phase and next_phase != prev_phase:
            self._seal_phase(prev_phase, evaluate_message)
        if next_phase:
            progress["current_phase_id"] = next_phase
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

        event = {
            "call_id": call_id,
            "tool": tool_name,
            "status": status,
            "target": target,
            "phase_id": phase_id or (self.progress or {}).get("current_phase_id"),
            "message": exec_result.get("message"),
            "kind": exec_result.get("kind") or ("query" if tool_name.startswith("get_") else "act"),
            "produced_objects": exec_result.get("produced_objects") or [],
        }
        self._push_recent_event(event)
        self._push_phase_event(event)

    def update_from_evaluate(self, evaluate_result: dict, high_level_plan: dict | None = None):
        message = evaluate_result.get("message")
        phase_status = evaluate_result.get("phase_status")
        step = evaluate_result.get("current_abstract_step")
        phase_id = (
            (step or {}).get("step_id")
            or evaluate_result.get("updated_current_phase_id")
            or evaluate_result.get("phase_id")
        )
        if phase_status == "completed" and message:
            # Prefer sealing under the previous phase id inside update_progress.
            summary = f"{(self.progress or {}).get('current_phase_id') or phase_id or '当前阶段'}: {message}"
            if summary not in self.completed_summaries:
                self.completed_summaries.append(summary)
                self.completed_summaries = self.completed_summaries[-COMPLETED_SUMMARY_MAX:]
        if evaluate_result.get("decision") == "repair" and message:
            self.pending_summaries = [line for line in self.pending_summaries if message not in line]
            self.pending_summaries.append(f"待修复: {message}")
            self.pending_summaries = self.pending_summaries[-5:]
        self.update_progress(
            current_phase_id=phase_id,
            current_abstract_step=step,
            abstract_step_queue=evaluate_result.get("abstract_step_queue"),
            high_level_plan=high_level_plan,
            evaluate_message=message,
        )

    def restore_from_pack(self, pack: dict | None):
        """Rebuild memory from a previously built pack (session recovery)."""
        if not isinstance(pack, dict):
            return
        if isinstance(pack.get("object_memory"), dict):
            self.object_memory = dict(pack["object_memory"])
        if isinstance(pack.get("query_cache"), dict):
            self.query_cache = dict(pack["query_cache"])
        if isinstance(pack.get("error_memory"), dict):
            self.error_memory = dict(pack["error_memory"])
        if isinstance(pack.get("recent_events"), list):
            self.recent_events = list(pack["recent_events"])
        if isinstance(pack.get("phase_events"), list):
            self.phase_events = list(pack["phase_events"])
        if isinstance(pack.get("phase_conclusions"), list):
            self.phase_conclusions = list(pack["phase_conclusions"])
        if isinstance(pack.get("progress"), dict):
            self.progress = dict(pack["progress"])
        if pack.get("current_target"):
            self.current_target = pack["current_target"]

    def build_pack(self) -> dict:
        return {
            "working_summary": self._build_working_summary(),
            "recent_events": list(self.recent_events[-RECENT_EVENTS_MAX:]),
            "phase_events": list(self.phase_events[-CURRENT_PHASE_EVENTS_MAX:]),
            "phase_conclusions": list(self.phase_conclusions[-PHASE_CONCLUSIONS_MAX:]),
            "object_memory": dict(self.object_memory),
            "error_memory": dict(self.error_memory),
            "query_cache": self._compact_query_cache(),
            "progress": dict(self.progress),
            "long_summary": self._build_long_summary(),
            "current_target": self.current_target,
        }

    def _seal_phase(self, phase_id: str, message: str | None = None):
        """Compress current-phase trajectory into a short conclusion, then reset."""
        if not phase_id:
            return
        produced: list[str] = []
        for entry in self.phase_events:
            for name in entry.get("produced_objects") or []:
                if name and name not in produced:
                    produced.append(name)
        ops = len(self.phase_events)
        summary = (message or "").strip() or f"{phase_id} 完成（{ops} 次操作）"
        if not summary.startswith(str(phase_id)):
            summary = f"{phase_id}: {summary}"
        self.phase_conclusions.append({
            "phase_id": phase_id,
            "summary": summary,
            "produced": produced[:12],
            "ops": ops,
        })
        self.phase_conclusions = self.phase_conclusions[-PHASE_CONCLUSIONS_MAX:]
        self.phase_events = []

    def _push_phase_event(self, entry: dict):
        self.phase_events.append(dict(entry))
        self.phase_events = self.phase_events[-CURRENT_PHASE_EVENTS_MAX:]

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
        facts = _extract_spatial_facts(query_result)
        for tgt in dict.fromkeys(targets):
            self.query_cache[tgt] = {
                "tool": tool_name,
                "call_id": call_id,
                "step_id": phase_id,
                "summary": summary,
                "query_result": query_result,
                "has_spatial_facts": bool(facts.get("size") and facts.get("center")),
                "size": facts.get("size"),
                "center": facts.get("center"),
            }
            # Propagate usable size/center into object index
            if tgt != "__document__" and facts.get("size"):
                entry = self.object_memory.setdefault(tgt, {})
                entry["size"] = facts["size"]
                if facts.get("center"):
                    entry["center"] = facts["center"]
                entry.setdefault("status", "queried")
                entry.setdefault("role", _infer_role(tgt))

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
                "has_spatial_facts": item.get("has_spatial_facts", False),
                "size": item.get("size"),
                "center": item.get("center"),
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
