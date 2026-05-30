# debug_settings.py — Debug mode preferences for AI CAD Agent

import os

import FreeCAD


_PARAM_GROUP = "User"
_PARAM_APP = "AICADAgent"


def is_debug_mode() -> bool:
    """Read debug mode from FreeCAD user parameters."""
    try:
        param = FreeCAD.ParamGet(_PARAM_GROUP, _PARAM_APP)
        return param.GetBool("DebugMode", False)
    except Exception:
        return False


def set_debug_mode(enabled: bool) -> None:
    try:
        param = FreeCAD.ParamGet(_PARAM_GROUP, _PARAM_APP)
        param.SetBool("DebugMode", bool(enabled))
    except Exception:
        pass


def get_debug_sessions_dir() -> str:
    """Default local path to agent_service/debug_sessions (for UI open-folder)."""
    try:
        param = FreeCAD.ParamGet(_PARAM_GROUP, _PARAM_APP)
        custom = param.GetString("DebugSessionsDir", "")
        if custom and os.path.isdir(custom):
            return custom
    except Exception:
        pass

    addon_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(addon_dir, "..", ".."))
    return os.path.join(project_root, "agent_service", "debug_sessions")
