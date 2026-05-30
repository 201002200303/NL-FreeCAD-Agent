# document_state.py — Enhanced FreeCAD document state extraction

import FreeCAD


def get_document_state() -> dict:
    """Read the current FreeCAD document state with enhanced geometric info.

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
        obj_info = _extract_object_state(obj)
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


def _extract_object_state(obj) -> dict:
    """Extract complete state from a FreeCAD object."""
    obj_info = {
        "name": obj.Name,
        "label": obj.Label,
        "type": obj.TypeId,
        "properties": _extract_properties(obj),
    }

    # Visibility
    try:
        obj_info["visible"] = obj.Visibility
    except Exception:
        obj_info["visible"] = True

    # Shape-based info (bbox, topology, placement)
    if _has_shape(obj):
        obj_info["bbox"] = _extract_bbox(obj)
        obj_info["topology"] = _extract_topology(obj)
        obj_info["placement"] = _extract_placement(obj)
    else:
        obj_info["bbox"] = None
        obj_info["topology"] = None
        obj_info["placement"] = None

    # Dependencies (full chain)
    obj_info["dependencies"] = _extract_dependencies(obj)

    return obj_info


def _has_shape(obj) -> bool:
    """Check if object has a Shape attribute."""
    try:
        return hasattr(obj, "Shape") and obj.Shape is not None
    except Exception:
        return False


def _extract_bbox(obj) -> dict | None:
    """Extract bounding box from object's Shape."""
    try:
        bbox = obj.Shape.BoundBox
        return {
            "xmin": bbox.XMin,
            "xmax": bbox.XMax,
            "ymin": bbox.YMin,
            "ymax": bbox.YMax,
            "zmin": bbox.ZMin,
            "zmax": bbox.ZMax,
            "center": [bbox.Center.x, bbox.Center.y, bbox.Center.z],
            "size": [bbox.XLength, bbox.YLength, bbox.ZLength],
        }
    except Exception:
        return None


def _extract_topology(obj) -> dict | None:
    """Extract topology summary from object's Shape."""
    try:
        shape = obj.Shape
        return {
            "faces": len(shape.Faces),
            "edges": len(shape.Edges),
            "vertices": len(shape.Vertexes),
            "solids": len(shape.Solids),
            "is_valid": shape.isValid(),
            "volume": shape.Volume if hasattr(shape, "Volume") else None,
            "area": shape.Area if hasattr(shape, "Area") else None,
        }
    except Exception:
        return None


def _extract_placement(obj) -> dict | None:
    """Extract placement (position + rotation) from object."""
    try:
        placement = obj.Placement
        base = placement.Base
        rot = placement.Rotation
        return {
            "base": [base.x, base.y, base.z],
            "rotation_euler": list(rot.toEuler()),
        }
    except Exception:
        return None


def _extract_dependencies(obj) -> dict:
    """Extract dependency chain (InList/OutList)."""
    try:
        return {
            "in_list": [o.Name for o in obj.InList],
            "out_list": [o.Name for o in obj.OutList],
        }
    except Exception:
        return {"in_list": [], "out_list": []}


def _extract_properties(obj) -> dict:
    """Extract relevant geometric properties from a FreeCAD object."""
    props = {}
    key_properties = [
        "Length", "Width", "Height", "Radius",
        "Angle",
    ]
    for prop_name in key_properties:
        try:
            value = getattr(obj, prop_name, None)
            if value is not None:
                try:
                    props[prop_name] = float(value)
                except (TypeError, ValueError):
                    props[prop_name] = str(value)
        except Exception:
            pass
    return props
