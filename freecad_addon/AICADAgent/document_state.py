# document_state.py — Enhanced FreeCAD document state extraction

import FreeCAD

from AICADAgent.geometry_facts import exact_bbox

_SKIP_TYPE_IDS = frozenset({
    "App::Origin", "App::Line", "App::Plane", "App::Point",
})


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
        if obj.TypeId in _SKIP_TYPE_IDS:
            continue
        objects.append(_extract_object_state(obj))

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
    shape_obj = _resolve_shape_source(obj)
    if shape_obj is not None:
        obj_info["bbox"] = _extract_bbox(shape_obj)
        obj_info["topology"] = _extract_topology(shape_obj)
        obj_info["placement"] = _extract_placement(obj)
        if obj_info["bbox"] is None and shape_obj is not obj:
            # Tip/fallback source may still fail; try original once more
            obj_info["bbox"] = _extract_bbox(obj)
    else:
        obj_info["bbox"] = None
        obj_info["topology"] = None
        obj_info["placement"] = _extract_placement(obj)

    # Dependencies (full chain)
    obj_info["dependencies"] = _extract_dependencies(obj)

    return obj_info


def _has_valid_shape(obj) -> bool:
    """True when object exposes a non-null FreeCAD Shape."""
    try:
        if not hasattr(obj, "Shape") or obj.Shape is None:
            return False
        shape = obj.Shape
        if hasattr(shape, "isNull") and shape.isNull():
            return False
        return True
    except Exception:
        return False


def _resolve_shape_source(obj):
    """Prefer the object itself; for empty Body fall back to Tip feature."""
    if _has_valid_shape(obj):
        return obj
    try:
        tip = getattr(obj, "Tip", None)
        if tip is not None and _has_valid_shape(tip):
            return tip
    except Exception:
        pass
    return None


def _bbox_to_dict(bbox) -> dict | None:
    try:
        return {
            "xmin": float(bbox.XMin),
            "xmax": float(bbox.XMax),
            "ymin": float(bbox.YMin),
            "ymax": float(bbox.YMax),
            "zmin": float(bbox.ZMin),
            "zmax": float(bbox.ZMax),
            "center": [
                float(bbox.Center.x),
                float(bbox.Center.y),
                float(bbox.Center.z),
            ],
            "size": [
                float(bbox.XLength),
                float(bbox.YLength),
                float(bbox.ZLength),
            ],
        }
    except Exception:
        return None


def _extract_bbox(obj) -> dict | None:
    """Extract world-space bounding box (includes placement/rotation).

    Uses exact_bbox (optimalBoundingBox) because the acceptance checks and the
    Agent both read this value, and Shape.BoundBox inflates curved solids.
    Part::Feature / loft / PartDesign objects may fail on obj.getBoundBox()
    even when the Shape bbox is valid (list_topology already proves this path).
    Try the shape bbox first, then a transformed copy, then obj.getBoundBox().
    """
    # 1) Direct shape bbox — same source list_topology uses successfully
    try:
        shape = obj.Shape
        if shape is not None and not (hasattr(shape, "isNull") and shape.isNull()):
            result = _bbox_to_dict(exact_bbox(shape))
            if result is not None:
                return result
    except Exception:
        pass

    # 2) Transformed Shape (world coords when Placement is non-identity)
    try:
        shape = obj.Shape
        if shape is not None and not (hasattr(shape, "isNull") and shape.isNull()):
            placement = (
                obj.getGlobalPlacement()
                if hasattr(obj, "getGlobalPlacement")
                else obj.Placement
            )
            shape_w = shape.copy()
            shape_w.transformShape(placement.toMatrix())
            result = _bbox_to_dict(exact_bbox(shape_w))
            if result is not None:
                return result
    except Exception:
        pass

    # 3) Object-level BoundBox API
    try:
        result = _bbox_to_dict(obj.getBoundBox())
        if result is not None:
            return result
    except Exception:
        pass
    return None


def _extract_topology(obj) -> dict | None:
    """Extract topology summary from object's Shape."""
    try:
        shape = obj.Shape
        if shape is None or (hasattr(shape, "isNull") and shape.isNull()):
            return None
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
