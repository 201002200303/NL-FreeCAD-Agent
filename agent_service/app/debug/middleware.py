"""Helpers for wiring trace logging into FastAPI endpoints."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from app.debug.trace_logger import (
    TraceSession,
    get_trace_session,
    is_debug_enabled,
    set_current_step_name,
    set_trace_session,
)


@contextmanager
def trace_api_step(
    session_id: str,
    endpoint: str,
    payload: dict,
    debug_mode: bool,
    *,
    phase_id: str | None = None,
    call_id: str | None = None,
    create_new: bool = False,
) -> Iterator[tuple[TraceSession | None, str | None]]:
    """Context manager: attach trace session, log request/response around handler."""
    trace: TraceSession | None = None
    step_name: str | None = None

    if is_debug_enabled(debug_mode):
        if create_new:
            trace = TraceSession.start(session_id)
        else:
            trace = TraceSession.open_existing(session_id) or TraceSession.start(session_id)
        set_trace_session(trace)
        step_name = trace.next_step_name(endpoint, phase_id=phase_id, call_id=call_id)
        set_current_step_name(step_name)
        trace.log_api_request(step_name, endpoint, payload, phase_id=phase_id)

    try:
        yield trace, step_name
    finally:
        set_trace_session(None)
        set_current_step_name(None)


def attach_debug_fields(response_obj: Any, trace: TraceSession | None, step_name: str | None) -> Any:
    """Set debug_session_path / debug_step_name on Pydantic response models."""
    if trace and step_name and hasattr(response_obj, "debug_session_path"):
        response_obj.debug_session_path = trace.path
        response_obj.debug_step_name = step_name
    return response_obj
