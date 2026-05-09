# document_state.py — Read current FreeCAD document state

import FreeCAD


def get_document_state() -> dict:
    """Read the current FreeCAD document state.

    Returns a dict suitable for sending to the Agent service.
    """
    doc = FreeCAD.ActiveDocument
    if doc is None:
        return {
            "document_name": "",
            "objects": [],
            "selected_objects": [],
        }

    objects = []
    for obj in doc.Objects:
        obj_info = {
            "name": obj.Name,
            "label": obj.Label,
            "type": obj.TypeId,
            "properties": _extract_properties(obj),
        }
        objects.append(obj_info)

    # Get selected objects
    selected = []
    try:
        import FreeCADGui
        sel = FreeCADGui.Selection.getSelection()
        selected = [o.Name for o in sel]
    except Exception:
        pass

    return {
        "document_name": doc.Name,
        "objects": objects,
        "selected_objects": selected,
    }


def _extract_properties(obj) -> dict:
    """Extract relevant geometric properties from a FreeCAD object."""
    props = {}
    key_properties = [
        "Length", "Width", "Height", "Radius",
        "Angle", "Placement", "Shape",
    ]
    for prop_name in key_properties:
        try:
            value = getattr(obj, prop_name, None)
            if value is not None:
                if prop_name == "Placement":
                    props[prop_name] = str(value)
                elif prop_name == "Shape":
                    props[prop_name] = f"<Shape object>"
                else:
                    # Convert to float for simple numeric properties
                    try:
                        props[prop_name] = float(value)
                    except (TypeError, ValueError):
                        props[prop_name] = str(value)
        except Exception:
            pass
    return props
