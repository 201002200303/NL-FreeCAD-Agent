"""Capture the active FreeCAD 3D view for vision checks."""

from __future__ import annotations

import base64
import os
import tempfile
from typing import Optional


def capture_viewport(max_edge: int = 1024) -> Optional[dict]:
    """Return {image_b64, mime} or None if GUI/view unavailable."""
    try:
        import FreeCADGui
    except ImportError:
        return None

    doc = FreeCADGui.ActiveDocument
    if doc is None:
        return None
    view = getattr(doc, "ActiveView", None)
    if view is None:
        return None

    path = tempfile.mktemp(suffix=".png")
    try:
        try:
            view.fitAll()
        except Exception:
            pass
        # FreeCAD: saveImage(filename, w, h, color="Current"|"White"|"Black"|"Transparent")
        view.saveImage(path, int(max_edge), int(max_edge), "Current")
        if not os.path.isfile(path) or os.path.getsize(path) < 32:
            return None
        with open(path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")
        return {"image_b64": b64, "mime": "image/png"}
    except Exception as exc:
        print(f"[AICAD] viewport capture failed: {exc}")
        return None
    finally:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
