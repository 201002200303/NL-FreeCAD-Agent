# debug_settings.py — Debug mode preferences for AI CAD Agent

import os
from typing import Optional

import FreeCAD


_PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/AICADAgent"


def _param_get():
    return FreeCAD.ParamGet(_PARAM_PATH)


def is_debug_mode() -> bool:
    """Read debug mode from FreeCAD user parameters."""
    try:
        return _param_get().GetBool("DebugMode", False)
    except Exception:
        return False


def set_debug_mode(enabled: bool) -> None:
    try:
        _param_get().SetBool("DebugMode", bool(enabled))
    except Exception:
        pass


def get_debug_sessions_dir() -> str:
    """Resolve agent_service/debug_sessions (same root the server writes to)."""
    try:
        custom = _param_get().GetString("DebugSessionsDir", "")
        if custom:
            custom = os.path.abspath(custom)
            if os.path.isdir(custom):
                return custom
    except Exception:
        pass

    addon_dir = os.path.dirname(os.path.abspath(__file__))
    current = addon_dir
    for _ in range(8):
        candidate = os.path.join(current, "agent_service", "debug_sessions")
        if os.path.isdir(os.path.join(current, "agent_service")):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    return os.path.join(
        os.path.abspath(os.path.join(addon_dir, "..", "..")),
        "agent_service",
        "debug_sessions",
    )


def resolve_debug_open_path(last_session_path: Optional[str] = None) -> str:
    """Prefer the active session folder, else the debug_sessions root."""
    if last_session_path:
        session_path = os.path.abspath(last_session_path)
        if os.path.isdir(session_path):
            return session_path
        parent = os.path.dirname(session_path)
        if os.path.isdir(parent):
            return parent
    return get_debug_sessions_dir()
