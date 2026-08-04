"""Reduce an ordered event stream into the current RunState.

The checkpoint stores a full run_state snapshot; the reducer replays events
recorded AFTER that checkpoint so recovery reflects everything that happened,
even if the process crashed before the next checkpoint was written.
"""

from __future__ import annotations

from typing import Optional

from app.runtime.events import EventType


def reduce_events(base_run_state: Optional[dict], events: list[dict]) -> dict:
    """Apply events (ascending seq) on top of a checkpoint run_state."""
    state: dict = dict(base_run_state or {})
    state.setdefault("completed_action_ids", [])
    state.setdefault("unresolved_errors", [])
    state.setdefault("completed_steps", [])
    state.setdefault("pending_action_ids", [])

    completed_actions = set(state.get("completed_action_ids") or [])
    pending_actions = set(state.get("pending_action_ids") or [])
    errors: list[dict] = list(state.get("unresolved_errors") or [])
    completed_steps: list[dict] = list(state.get("completed_steps") or [])

    for event in events:
        etype = event.get("event_type")
        payload = event.get("payload") or {}
        action_id = event.get("action_id")
        phase_id = event.get("phase_id")

        if etype == EventType.PLAN_CREATED:
            state["goal"] = payload.get("goal") or state.get("goal")

        elif etype == EventType.STEP_STARTED:
            state["current_phase_id"] = phase_id or state.get("current_phase_id")
            state["last_decision"] = payload.get("decision")

        elif etype == EventType.TOOL_STARTED:
            if action_id:
                pending_actions.add(action_id)

        elif etype == EventType.TOOL_SUCCEEDED:
            if action_id:
                completed_actions.add(action_id)
                pending_actions.discard(action_id)
            if payload.get("document_revision"):
                state["document_revision"] = payload["document_revision"]

        elif etype == EventType.TOOL_FAILED:
            if action_id:
                pending_actions.discard(action_id)
            errors.append(
                {
                    "action_id": action_id,
                    "tool": payload.get("tool"),
                    "message": payload.get("message"),
                    "phase_id": phase_id,
                }
            )

        elif etype == EventType.STEP_COMPLETED:
            state["current_phase_id"] = phase_id or state.get("current_phase_id")
            completed_steps.append(
                {
                    "phase_id": phase_id,
                    "decision": payload.get("decision"),
                    "message": payload.get("message"),
                }
            )
            # A completed step means its errors were dealt with (repair/skip)
            if payload.get("decision") in {"continue", "skip_and_continue"}:
                errors = []
            if payload.get("document_revision"):
                state["document_revision"] = payload["document_revision"]

        elif etype == EventType.STEP_REPLANNED:
            state["current_phase_id"] = phase_id or state.get("current_phase_id")
            state["last_decision"] = payload.get("decision")

        elif etype == EventType.USER_PAUSED:
            state["status"] = "paused"

        elif etype == EventType.USER_RESUMED:
            state["status"] = "running"

        elif etype == EventType.DOCUMENT_CHANGED_BY_USER:
            changes = state.setdefault("user_document_changes", [])
            changes.append(
                {
                    "seq": event.get("seq"),
                    "summary": payload.get("summary"),
                    "added": payload.get("added"),
                    "removed": payload.get("removed"),
                }
            )

        elif etype == EventType.SESSION_COMPLETED:
            state["status"] = "completed"

        elif etype == EventType.SESSION_ABORTED:
            state["status"] = "aborted"

    state["completed_action_ids"] = sorted(completed_actions)
    state["pending_action_ids"] = sorted(pending_actions)
    state["unresolved_errors"] = errors[-8:]
    state["completed_steps"] = completed_steps[-20:]
    return state
