# query_tools.py — Geometry query tools for precise CAD grounding

from AICADAgent.cad_tools._helpers import get_object, get_shape, analyze_topology
from AICADAgent.document_state import _extract_object_state


def list_topology(doc, target=""):
    """List faces/edges with indices, centers, normals — use before fillet/chamfer/pad-on-face."""
    obj = get_object(doc, target)
    shape = get_shape(obj)
    info = analyze_topology(shape)
    bbox = info.get("bbox") or {}
    # Normalize topology bbox so session_memory / agent can read size+center
    if isinstance(bbox, dict) and all(k in bbox for k in ("x", "y", "z")):
        try:
            xmin, xmax = float(bbox["x"][0]), float(bbox["x"][1])
            ymin, ymax = float(bbox["y"][0]), float(bbox["y"][1])
            zmin, zmax = float(bbox["z"][0]), float(bbox["z"][1])
            info["bbox"] = {
                "x": bbox["x"],
                "y": bbox["y"],
                "z": bbox["z"],
                "xmin": xmin,
                "xmax": xmax,
                "ymin": ymin,
                "ymax": ymax,
                "zmin": zmin,
                "zmax": zmax,
                "size": [xmax - xmin, ymax - ymin, zmax - zmin],
                "center": [
                    (xmin + xmax) / 2,
                    (ymin + ymax) / 2,
                    (zmin + zmax) / 2,
                ],
            }
        except (TypeError, ValueError, IndexError, KeyError):
            pass
    return _query_result(
        "list_topology",
        query_target=obj.Name,
        query_result={
            "name": obj.Name,
            "type": obj.TypeId,
            **info,
        },
    )


def summarize_document(doc):
    """Return a compact object tree and bbox summary for the active document."""
    objects = []
    for obj in doc.Objects:
        try:
            state = _extract_object_state(obj)
        except Exception:
            continue
        bbox = state.get("bbox") or {}
        objects.append({
            "name": state.get("name"),
            "label": state.get("label"),
            "type": state.get("type"),
            "visible": state.get("visible", True),
            "bbox": bbox,
            "size": bbox.get("size"),
            "center": bbox.get("center"),
            "dependencies": state.get("dependencies"),
        })
    return _query_result(
        "summarize_document",
        query_result={
            "document_name": doc.Name,
            "object_count": len(objects),
            "objects": objects,
        },
    )


def get_object_detail(doc, target=""):
    """Return detailed geometry facts for one object."""
    obj = get_object(doc, target)
    state = _extract_object_state(obj)
    # If document_state missed bbox but Shape is valid, fill from topology path
    if not state.get("bbox"):
        try:
            shape = get_shape(obj)
            info = analyze_topology(shape)
            bb = info.get("bbox") or {}
            if all(k in bb for k in ("x", "y", "z")):
                xmin, xmax = float(bb["x"][0]), float(bb["x"][1])
                ymin, ymax = float(bb["y"][0]), float(bb["y"][1])
                zmin, zmax = float(bb["z"][0]), float(bb["z"][1])
                state["bbox"] = {
                    "xmin": xmin,
                    "xmax": xmax,
                    "ymin": ymin,
                    "ymax": ymax,
                    "zmin": zmin,
                    "zmax": zmax,
                    "size": [xmax - xmin, ymax - ymin, zmax - zmin],
                    "center": [
                        (xmin + xmax) / 2,
                        (ymin + ymax) / 2,
                        (zmin + zmax) / 2,
                    ],
                }
        except Exception:
            pass
    return _query_result(
        "get_object_detail",
        query_target=obj.Name,
        query_result=state,
    )


def _object_bbox(obj):
    """BoundBox via Shape (FC 1.1+ PrimitivePy has no getBoundBox)."""
    try:
        return get_shape(obj).BoundBox
    except Exception:
        pass
    if hasattr(obj, "getBoundBox"):
        return obj.getBoundBox()
    raise ValueError(f"Object '{getattr(obj, 'Name', obj)}' has no usable BoundBox")


def measure_gap(doc, obj_a="", obj_b="", axis="X", tolerance=0.5):
    """Measure bbox gap/overlap between two objects along one world axis."""
    a = get_object(doc, obj_a)
    b = get_object(doc, obj_b)
    bb_a = _object_bbox(a)
    bb_b = _object_bbox(b)
    measurement = _measure_bbox_gap(bb_a, bb_b, axis, tolerance)
    measurement.update({
        "obj_a": a.Name,
        "obj_b": b.Name,
    })
    return _query_result(
        "measure_gap",
        query_targets=[a.Name, b.Name],
        query_result=measurement,
    )


def compare_orientation(doc, target="", expected_axis="Z", tolerance_ratio=0.2):
    """Compare expected axis with bbox-derived orientation.

    For cylinders/wheels, the meaningful axis is usually the thinnest bbox
    dimension after rotation. For other objects, the dominant dimension is used.
    tolerance_ratio marks an object as isotropic (orientation undetermined)
    when the dominant vs thin dimension differ by less than that ratio.
    """
    obj = get_object(doc, target)
    bb = _object_bbox(obj)
    sizes = {
        "X": float(bb.XLength),
        "Y": float(bb.YLength),
        "Z": float(bb.ZLength),
    }
    expected = str(expected_axis or "Z").upper()
    if expected not in sizes:
        raise ValueError(f"Invalid expected_axis: {expected_axis}")

    is_cylinder = "Cylinder" in getattr(obj, "TypeId", "") or "wheel" in obj.Name.lower()
    dominant_axis = max(sizes, key=sizes.get)
    thin_axis = min(sizes, key=sizes.get)
    dominant_size = sizes[dominant_axis]
    thin_size = sizes[thin_axis]

    ratio = float(tolerance_ratio)
    isotropic = dominant_size > 0 and (dominant_size - thin_size) / dominant_size < ratio
    if isotropic:
        actual_axis = expected
        passed = True
        note = "对象近似各向同性（各向尺寸接近），无法从 bbox 可靠判断朝向"
        delta = dominant_size - thin_size
    else:
        actual_axis = thin_axis if is_cylinder else dominant_axis
        passed = actual_axis == expected
        note = None
        delta = abs(sizes[actual_axis] - sizes[expected])

    return _query_result(
        "compare_orientation",
        query_target=obj.Name,
        query_result={
            "name": obj.Name,
            "type": obj.TypeId,
            "expected_axis": expected,
            "actual_axis": actual_axis,
            "dominant_axis": dominant_axis,
            "thin_axis": thin_axis,
            "sizes": sizes,
            "passed": passed,
            "isotropic": isotropic,
            "note": note,
            "delta": delta,
            "tolerance_ratio": tolerance_ratio,
        },
    )


def _query_result(tool, *, query_target=None, query_targets=None, query_result=None):
    result = {
        "kind": "query",
        "tool": tool,
        "query_result": query_result or {},
    }
    if query_target:
        result["query_target"] = query_target
    if query_targets:
        result["query_targets"] = query_targets
    return result


def _measure_bbox_gap(bb_a, bb_b, axis, tolerance):
    axis = str(axis or "X").upper()
    ranges = {
        "X": (bb_a.XMin, bb_a.XMax, bb_b.XMin, bb_b.XMax),
        "Y": (bb_a.YMin, bb_a.YMax, bb_b.YMin, bb_b.YMax),
        "Z": (bb_a.ZMin, bb_a.ZMax, bb_b.ZMin, bb_b.ZMax),
    }
    if axis not in ranges:
        raise ValueError(f"Invalid axis: {axis}")
    a_min, a_max, b_min, b_max = [float(v) for v in ranges[axis]]
    overlap = max(0.0, min(a_max, b_max) - max(a_min, b_min))
    if overlap > 0:
        signed_distance = 0.0
        gap = 0.0
    elif a_max <= b_min:
        signed_distance = b_min - a_max
        gap = signed_distance
    else:
        signed_distance = b_max - a_min
        gap = abs(signed_distance)
    return {
        "axis": axis,
        "range_a": [a_min, a_max],
        "range_b": [b_min, b_max],
        "gap": gap,
        "overlap": overlap,
        "signed_distance": signed_distance,
        "touching": gap <= float(tolerance),
        "tolerance": float(tolerance),
    }
