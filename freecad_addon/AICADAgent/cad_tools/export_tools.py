# export_tools.py — Export tools: STEP, STL, FCStd save


def save_fcstd(doc, filepath=""):
    """Save the FreeCAD document to the given path."""
    doc.saveAs(filepath)
    return {"tool": "save_fcstd", "filepath": filepath}
