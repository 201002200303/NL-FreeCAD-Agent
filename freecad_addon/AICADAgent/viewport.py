"""Capture FreeCAD 3D views for vision checks."""

from __future__ import annotations

import base64
import os
import tempfile
from typing import Optional

# FreeCAD ActiveView helpers → 标准工程视图
_VIEW_METHODS = {
    "front": "viewFront",
    "back": "viewRear",
    "side": "viewRight",
    "right": "viewRight",
    "left": "viewLeft",
    "top": "viewTop",
    "bottom": "viewBottom",
    "iso": "viewIsometric",
    "isometric": "viewIsometric",
}

DEFAULT_VIEWS = ("front", "side", "top", "iso")
MAX_CAPTURE_VIEWS = 4


def normalize_view_names(names: Optional[list[str]] = None) -> list[str]:
    """去重并限制数量；非法名保留但 capture 时会跳过定向。"""
    wanted = list(names or DEFAULT_VIEWS)
    out: list[str] = []
    seen: set[str] = set()
    for raw in wanted:
        key = str(raw or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= MAX_CAPTURE_VIEWS:
            break
    return out or list(DEFAULT_VIEWS)


def extract_tool_capture_images(tool_results: Optional[list] = None) -> list[dict]:
    """从本批 tool_results 取出 capture_views 成功截图（取最后一次成功）。"""
    images: list[dict] = []
    for item in tool_results or []:
        if not isinstance(item, dict):
            continue
        call = item.get("tool_call") or {}
        er = item.get("execution_result") or {}
        if call.get("tool") != "capture_views":
            continue
        if (er.get("status") or "").lower() != "success":
            continue
        imgs = er.get("viewport_images") or []
        if imgs:
            images = list(imgs)
    return images


def should_autofill_multiview(tool_results: Optional[list] = None) -> bool:
    """建模成功且本批未调用 capture_views → 客户端可补拍四视图。"""
    had_capture = False
    cad_ok = False
    for item in tool_results or []:
        if not isinstance(item, dict):
            continue
        call = item.get("tool_call") or {}
        er = item.get("execution_result") or {}
        tool = call.get("tool") or er.get("tool")
        if tool == "capture_views":
            had_capture = True
        if tool == "execute_cad_program" and (er.get("status") or "").lower() == "success":
            cad_ok = True
    return cad_ok and not had_capture


def capture_viewport(max_edge: int = 1024) -> Optional[dict]:
    """Return {image_b64, mime, name} or None if GUI/view unavailable."""
    views = capture_views(["iso"], max_edge=max_edge)
    return views[0] if views else None


def capture_views(
    names: Optional[list[str]] = None,
    *,
    max_edge: int = 1024,
) -> list[dict]:
    """截取多视图。任一视图失败则跳过该视图；全部失败返回 []（调用方降级）。"""
    try:
        import FreeCADGui
    except ImportError:
        return []

    doc = FreeCADGui.ActiveDocument
    if doc is None:
        return []
    view = getattr(doc, "ActiveView", None)
    if view is None:
        return []

    wanted = normalize_view_names(names)
    out: list[dict] = []
    for name in wanted:
        method = _VIEW_METHODS.get((name or "").lower())
        if method and hasattr(view, method):
            try:
                getattr(view, method)()
            except Exception as exc:
                print(f"[AICAD] view {name} orient failed: {exc}")
                continue
        shot = _save_current_view(view, name=name, max_edge=max_edge)
        if shot:
            out.append(shot)
    # 尽量回到等轴测，方便用户继续看
    try:
        if hasattr(view, "viewIsometric"):
            view.viewIsometric()
    except Exception:
        pass
    return out


def _save_current_view(view, *, name: str, max_edge: int) -> Optional[dict]:
    path = tempfile.mktemp(suffix=".png")
    try:
        try:
            view.fitAll()
        except Exception:
            pass
        view.saveImage(path, int(max_edge), int(max_edge), "Current")
        if not os.path.isfile(path) or os.path.getsize(path) < 32:
            return None
        with open(path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")
        return {"name": name, "image_b64": b64, "mime": "image/png"}
    except Exception as exc:
        print(f"[AICAD] viewport capture failed ({name}): {exc}")
        return None
    finally:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
