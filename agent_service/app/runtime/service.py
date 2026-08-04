"""High-level runtime service used by API endpoints."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Optional

from app.runtime.diff import compact_objects, diff_documents
from app.runtime.events import EventType
from app.runtime.reducer import reduce_events
from app.runtime.store import RuntimeStore

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "runtime.db"
_runtime: Optional["RuntimeService"] = None


def _default_db_path() -> Path:
    override = os.getenv("RUNTIME_DB_PATH", "").strip()
    if override:
        return Path(override)
    return _DEFAULT_DB


class RuntimeService:
    def __init__(self, db_path: str | Path | None = None):
        self.store = RuntimeStore(db_path or _default_db_path())

    def start_session(
        self,
        session_id: str,
        *,
        user_input: str,
        goal: str = "",
        plan: Optional[dict] = None,
        document_state: Optional[dict] = None,
    ) -> dict:
        self.store.create_session(
            session_id,
            user_input=user_input,
            user_goal=goal,
            plan_json=plan or {},
            status="running",
        )
        self.store.append_event(
            session_id,
            EventType.SESSION_STARTED,
            payload={
                "user_input": user_input,
                "goal": goal,
                "document_name": (document_state or {}).get("document_name"),
                "object_count": len((document_state or {}).get("objects") or []),
            },
        )
        if plan:
            self.store.append_event(
                session_id,
                EventType.PLAN_CREATED,
                payload={
                    "goal": goal or plan.get("goal"),
                    "phases": [
                        {
                            "phase_id": p.get("phase_id"),
                            "title": p.get("title"),
                            "intent": p.get("intent"),
                        }
                        for p in (plan.get("phases") or [])
                        if isinstance(p, dict)
                    ],
                },
            )
        return self.save_checkpoint(
            session_id,
            status="running",
            run_state={
                "user_input": user_input,
                "goal": goal or (plan or {}).get("goal", ""),
                "high_level_plan": plan or {},
                "current_phase_id": ((plan or {}).get("phases") or [{}])[0].get("phase_id")
                if (plan or {}).get("phases")
                else None,
                "abstract_step_queue": (plan or {}).get("abstract_step_queue"),
                "current_abstract_step": (plan or {}).get("current_abstract_step"),
                "document_revision": _document_revision(document_state),
            },
        )

    def record_next_step(
        self,
        session_id: str,
        *,
        phase_id: Optional[str],
        decision: str,
        tool_calls: list[dict],
        message: Optional[str] = None,
        current_abstract_step: Optional[dict] = None,
        document_state: Optional[dict] = None,
    ) -> None:
        step_id = (current_abstract_step or {}).get("step_id") or phase_id
        self.store.append_event(
            session_id,
            EventType.STEP_STARTED,
            phase_id=phase_id,
            step_id=step_id,
            payload={
                "decision": decision,
                "message": message,
                "tool_count": len(tool_calls or []),
                "tools": [c.get("tool") for c in (tool_calls or [])],
                "document_revision": _document_revision(document_state),
            },
        )
        if decision in {"abort", "ask_user"}:
            return
        for call in tool_calls or []:
            self.store.append_event(
                session_id,
                EventType.TOOL_STARTED,
                action_id=call.get("call_id"),
                phase_id=phase_id,
                step_id=step_id,
                payload={
                    "tool": call.get("tool"),
                    "args": call.get("args") or {},
                    "description": call.get("description"),
                },
            )

    def record_tool_result(
        self,
        session_id: str,
        *,
        tool_call: dict,
        execution_result: dict,
        phase_id: Optional[str] = None,
        document_state: Optional[dict] = None,
    ) -> None:
        status = (execution_result or {}).get("status", "unknown")
        event_type = (
            EventType.TOOL_SUCCEEDED
            if status == "success"
            else EventType.TOOL_FAILED
        )
        self.store.append_event(
            session_id,
            event_type,
            action_id=(tool_call or {}).get("call_id") or (execution_result or {}).get("call_id"),
            phase_id=phase_id,
            payload={
                "tool": (tool_call or {}).get("tool") or (execution_result or {}).get("tool"),
                "status": status,
                "message": (execution_result or {}).get("message"),
                "produced_objects": (execution_result or {}).get("produced_objects") or [],
                "kind": (execution_result or {}).get("kind"),
                "query_target": (execution_result or {}).get("query_target"),
                "query_summary": _query_summary((execution_result or {}).get("query_result")),
                "document_revision": _document_revision(document_state),
            },
        )

    def record_evaluate(
        self,
        session_id: str,
        *,
        evaluate_result: dict,
        phase_id: Optional[str] = None,
        document_state: Optional[dict] = None,
        high_level_plan: Optional[dict] = None,
        abstract_step_queue: Optional[dict] = None,
        current_abstract_step: Optional[dict] = None,
        session_memory: Optional[dict] = None,
        name_map: Optional[dict] = None,
    ) -> dict:
        decision = (evaluate_result or {}).get("decision", "continue")
        updated_phase = (evaluate_result or {}).get("updated_current_phase_id") or phase_id
        step = current_abstract_step or (evaluate_result or {}).get("current_abstract_step")
        queue = abstract_step_queue or (evaluate_result or {}).get("abstract_step_queue")

        event_type = EventType.STEP_COMPLETED
        if decision in {"repair", "replan"}:
            event_type = EventType.STEP_REPLANNED
        elif decision in {"abort"}:
            event_type = EventType.SESSION_ABORTED
        elif decision == "finish":
            event_type = EventType.SESSION_COMPLETED

        self.store.append_event(
            session_id,
            event_type,
            phase_id=updated_phase,
            step_id=(step or {}).get("step_id"),
            payload={
                "decision": decision,
                "phase_status": (evaluate_result or {}).get("phase_status"),
                "message": (evaluate_result or {}).get("message"),
                "deterministic_issues": (evaluate_result or {}).get("deterministic_issues") or [],
                "document_revision": _document_revision(document_state),
            },
        )

        status = "completed" if decision == "finish" else ("aborted" if decision == "abort" else "running")
        run_state = {
            "high_level_plan": high_level_plan or {},
            "current_phase_id": updated_phase,
            "abstract_step_queue": queue,
            "current_abstract_step": step,
            "session_memory": session_memory or {},
            "name_map": name_map or {},
            "last_evaluate": {
                "decision": decision,
                "phase_status": (evaluate_result or {}).get("phase_status"),
                "message": (evaluate_result or {}).get("message"),
            },
            "document_revision": _document_revision(document_state),
        }
        return self.save_checkpoint(session_id, status=status, run_state=run_state)

    def save_checkpoint(
        self,
        session_id: str,
        *,
        status: str,
        run_state: dict,
        checkpoint_id: Optional[str] = None,
    ) -> dict:
        cid = checkpoint_id or f"ckpt_{uuid.uuid4().hex[:10]}"
        checkpoint = self.store.save_checkpoint(
            session_id,
            cid,
            status=status,
            run_state=run_state,
        )
        self.store.append_event(
            session_id,
            EventType.CHECKPOINT_SAVED,
            payload={
                "checkpoint_id": cid,
                "status": status,
                "event_seq": checkpoint.get("event_seq"),
                "current_phase_id": (run_state or {}).get("current_phase_id"),
            },
        )
        return checkpoint

    def load_checkpoint(self, session_id: str) -> Optional[dict]:
        return self.store.latest_checkpoint(session_id)

    # ── Lifecycle: pause / resume / recovery ─────────────────────────

    def pause_session(
        self,
        session_id: str,
        *,
        document_state: Optional[dict] = None,
        reason: str = "",
    ) -> dict:
        """Persist a USER_PAUSED event + checkpoint carrying a document snapshot."""
        snapshot = compact_objects(document_state)
        self.store.append_event(
            session_id,
            EventType.USER_PAUSED,
            payload={
                "reason": reason,
                "document_revision": _document_revision(document_state),
                "object_count": len(snapshot),
            },
        )
        checkpoint = self.store.latest_checkpoint(session_id) or {}
        run_state = dict(checkpoint.get("run_state") or {})
        run_state["paused_document_objects"] = snapshot
        run_state["document_revision"] = _document_revision(document_state)
        return self.save_checkpoint(session_id, status="paused", run_state=run_state)

    def resume_session(
        self,
        session_id: str,
        *,
        document_state: Optional[dict] = None,
    ) -> dict:
        """Resume a session: detect user edits made while paused, rebuild RunState.

        Returns {run_state, document_changes, events_replayed, checkpoint_id}.
        The caller (FreeCAD client) restores plan/queue/memory from run_state.
        """
        checkpoint = self.store.latest_checkpoint(session_id)
        base_run_state = dict((checkpoint or {}).get("run_state") or {})
        after_seq = int((checkpoint or {}).get("event_seq") or 0)

        # Replay events recorded after the checkpoint (crash tolerance)
        new_events = self.store.list_events(session_id, after_seq=after_seq)
        run_state = reduce_events(base_run_state, new_events)
        run_state["completed_action_ids"] = sorted(
            set(run_state.get("completed_action_ids") or [])
            | self.store.action_ids_with_event(session_id, EventType.TOOL_SUCCEEDED)
        )

        # Detect manual document edits while paused / offline
        document_changes = None
        reference = run_state.get("paused_document_objects")
        if reference is None and document_state is not None:
            # No pause snapshot — fall back to revision string comparison
            old_rev = run_state.get("document_revision")
            new_rev = _document_revision(document_state)
            if old_rev and new_rev and old_rev != new_rev:
                document_changes = {
                    "changed": True,
                    "added": [],
                    "removed": [],
                    "modified": [],
                    "summary": "文档指纹变化（无暂停快照，无法给出对象级 diff）",
                }
        elif reference is not None and document_state is not None:
            result = diff_documents(reference, document_state)
            if result["changed"]:
                document_changes = result

        if document_changes:
            self.store.append_event(
                session_id,
                EventType.DOCUMENT_CHANGED_BY_USER,
                payload={
                    "summary": document_changes.get("summary"),
                    "added": document_changes.get("added"),
                    "removed": document_changes.get("removed"),
                    "modified": [
                        {"name": m.get("name"), "changes": m.get("changes")}
                        for m in (document_changes.get("modified") or [])
                    ],
                },
            )
            changes = run_state.setdefault("user_document_changes", [])
            changes.append({"summary": document_changes.get("summary")})

        self.store.append_event(
            session_id,
            EventType.USER_RESUMED,
            payload={
                "events_replayed": len(new_events),
                "document_changed": bool(document_changes),
            },
        )

        run_state["status"] = "running"
        run_state.pop("paused_document_objects", None)
        run_state["document_revision"] = _document_revision(document_state) or run_state.get(
            "document_revision"
        )
        new_checkpoint = self.save_checkpoint(
            session_id, status="running", run_state=run_state
        )
        return {
            "run_state": run_state,
            "document_changes": document_changes,
            "events_replayed": len(new_events),
            "checkpoint_id": new_checkpoint.get("checkpoint_id"),
        }

    def get_session_snapshot(self, session_id: str, *, recent_limit: int = 20) -> Optional[dict]:
        """Full recovery view: session row + reduced run_state + recent events."""
        session = self.store.get_session(session_id)
        if session is None:
            return None
        checkpoint = self.store.latest_checkpoint(session_id)
        after_seq = int((checkpoint or {}).get("event_seq") or 0)
        new_events = self.store.list_events(session_id, after_seq=after_seq)
        run_state = reduce_events(dict((checkpoint or {}).get("run_state") or {}), new_events)
        return {
            "session": session,
            "checkpoint_id": (checkpoint or {}).get("checkpoint_id"),
            "run_state": run_state,
            "recent_events": self.store.recent_events(session_id, limit=recent_limit),
            "completed_action_ids": sorted(
                self.store.action_ids_with_event(session_id, EventType.TOOL_SUCCEEDED)
            ),
        }

    def list_sessions(self, limit: int = 20) -> list[dict]:
        return self.store.list_sessions(limit=limit)

    def completed_action_ids(self, session_id: str) -> set[str]:
        """action_ids that already recorded TOOL_SUCCEEDED (idempotency guard)."""
        return self.store.action_ids_with_event(session_id, EventType.TOOL_SUCCEEDED)

    def build_context_slice(
        self,
        session_id: str,
        *,
        document_state: Optional[dict] = None,
        session_memory: Optional[dict] = None,
        current_phase_id: Optional[str] = None,
        current_abstract_step: Optional[dict] = None,
        recent_limit: int = 10,
    ) -> dict:
        """Build the dynamic LLM context projection from durable runtime state."""
        session = self.store.get_session(session_id) or {}
        checkpoint = self.store.latest_checkpoint(session_id)
        events = self.store.recent_events(session_id, limit=recent_limit)
        memory = session_memory or (checkpoint or {}).get("run_state", {}).get("session_memory") or {}

        unresolved_errors = []
        last_error = (memory.get("error_memory") or {}).get("last_error")
        if last_error:
            unresolved_errors.append(last_error)
        for event in events:
            if event["event_type"] == EventType.TOOL_FAILED:
                unresolved_errors.append(
                    {
                        "tool": (event.get("payload") or {}).get("tool"),
                        "message": (event.get("payload") or {}).get("message"),
                        "action_id": event.get("action_id"),
                        "phase_id": event.get("phase_id"),
                    }
                )

        completed = []
        for event in events:
            if event["event_type"] in {EventType.STEP_COMPLETED, EventType.PLAN_CREATED}:
                payload = event.get("payload") or {}
                if event["event_type"] == EventType.PLAN_CREATED:
                    completed.append(
                        {
                            "kind": "plan",
                            "goal": payload.get("goal"),
                            "phases": payload.get("phases") or [],
                        }
                    )
                else:
                    completed.append(
                        {
                            "kind": "step",
                            "phase_id": event.get("phase_id"),
                            "decision": payload.get("decision"),
                            "message": payload.get("message"),
                        }
                    )

        related_objects = _select_related_objects(
            document_state,
            memory,
            current_abstract_step,
        )

        user_changes = [
            {
                "seq": e["seq"],
                "summary": (e.get("payload") or {}).get("summary"),
                "added": (e.get("payload") or {}).get("added"),
                "removed": (e.get("payload") or {}).get("removed"),
            }
            for e in events
            if e["event_type"] == EventType.DOCUMENT_CHANGED_BY_USER
        ]

        return {
            "session_id": session_id,
            "status": session.get("status") or (checkpoint or {}).get("status"),
            "user_goal": session.get("user_goal") or memory.get("progress", {}).get("goal"),
            "current_phase_id": current_phase_id
            or (checkpoint or {}).get("run_state", {}).get("current_phase_id"),
            "current_step": current_abstract_step
            or (checkpoint or {}).get("run_state", {}).get("current_abstract_step"),
            "related_cad_objects": related_objects,
            "recent_events": [
                {
                    "seq": e["seq"],
                    "type": e["event_type"],
                    "action_id": e.get("action_id"),
                    "phase_id": e.get("phase_id"),
                    "payload": e.get("payload") or {},
                    "created_at": e.get("created_at"),
                }
                for e in events
            ],
            "unresolved_errors": unresolved_errors[-5:],
            "user_document_changes": user_changes[-3:],
            "completed_stage_summaries": completed[-8:],
            "checkpoint_id": (checkpoint or {}).get("checkpoint_id"),
            "document_revision": _document_revision(document_state),
        }


def get_runtime() -> RuntimeService:
    global _runtime
    if _runtime is None:
        _runtime = RuntimeService()
    return _runtime


def reset_runtime_for_tests(db_path: str | Path) -> RuntimeService:
    global _runtime
    _runtime = RuntimeService(db_path)
    return _runtime


def _document_revision(document_state: Optional[dict]) -> Optional[str]:
    if not document_state:
        return None
    objects = document_state.get("objects") or []
    names = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        name = obj.get("name") or ""
        obj_type = obj.get("type") or ""
        bbox = obj.get("bbox") or {}
        size = bbox.get("size") if isinstance(bbox, dict) else None
        names.append(f"{name}:{obj_type}:{size}")
    return f"{document_state.get('document_name', '')}|{len(objects)}|{'|'.join(names[:40])}"


def _query_summary(query_result: Optional[dict]) -> str:
    if not query_result:
        return ""
    parts = []
    if query_result.get("name"):
        parts.append(f"name={query_result['name']}")
    bbox = query_result.get("bbox") or {}
    if isinstance(bbox, dict):
        if bbox.get("size"):
            parts.append(f"size={bbox['size']}")
        if bbox.get("center"):
            parts.append(f"center={bbox['center']}")
    return "; ".join(parts)


def _select_related_objects(
    document_state: Optional[dict],
    memory: dict,
    current_abstract_step: Optional[dict],
) -> list[dict]:
    objects = (document_state or {}).get("objects") or []
    object_memory = memory.get("object_memory") or {}
    current_target = memory.get("current_target")
    intent = ((current_abstract_step or {}).get("intent") or "").lower()

    selected: list[dict] = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        name = obj.get("name") or ""
        role = (object_memory.get(name) or {}).get("role", "")
        keep = False
        if current_target and name == current_target:
            keep = True
        elif role and role in intent:
            keep = True
        elif name.lower() in intent:
            keep = True
        elif obj.get("bbox"):
            # keep solids with bbox as primary spatial anchors
            topo = obj.get("topology") or {}
            if topo.get("solids"):
                keep = True
        if not keep:
            continue
        selected.append(
            {
                "name": name,
                "type": obj.get("type"),
                "role": role or None,
                "bbox": obj.get("bbox"),
                "placement": obj.get("placement"),
                "visible": obj.get("visible"),
            }
        )
        if len(selected) >= 12:
            break

    if not selected and object_memory:
        for name, info in list(object_memory.items())[:8]:
            selected.append(
                {
                    "name": name,
                    "type": info.get("type"),
                    "role": info.get("role"),
                    "size": info.get("size"),
                    "center": info.get("center"),
                    "status": info.get("status"),
                }
            )
    return selected
