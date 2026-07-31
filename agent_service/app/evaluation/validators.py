from math import isclose
from typing import Any


def run_geometry_validators(
    validators: list[str],
    *,
    before_state: Any = None,
    after_state: Any = None,
    tool_call: dict | None = None,
    execution_result: dict | None = None,
    expectations: dict | None = None,
) -> list[dict]:
    results = []
    for name in validators:
        fn = VALIDATORS.get(name)
        if fn is None:
            results.append(_result(name, False, "UNKNOWN_VALIDATOR", f"Unknown validator: {name}"))
            continue
        results.append(fn(before_state, after_state, tool_call or {}, execution_result or {}, expectations or {}))
    return results


def verify_object_exists(before_state, after_state, tool_call, execution_result, expectations):
    name = _expected_object_name(tool_call, execution_result, expectations)
    if not name:
        return _result("verify_object_exists", False, "OBJECT_NAME_MISSING", "No expected object name was provided.")
    obj = _get_object(after_state, name)
    if obj is None:
        return _result("verify_object_exists", False, "OBJECT_NOT_FOUND", f"Object '{name}' was not found.")
    return _result("verify_object_exists", True, None, f"Object '{name}' exists.")


def verify_shape_valid(before_state, after_state, tool_call, execution_result, expectations):
    name = _expected_object_name(tool_call, execution_result, expectations)
    obj = _get_object(after_state, name)
    if obj is None:
        return _result("verify_shape_valid", False, "OBJECT_NOT_FOUND", f"Object '{name}' was not found.")
    topo = _get_attr(obj, "topology")
    valid = True if topo is None else bool(_get_attr(topo, "is_valid", True))
    message = f"Object '{name}' shape is valid." if valid else f"Object '{name}' has invalid shape."
    return _result("verify_shape_valid", valid, "SHAPE_INVALID", message)


def verify_solid_count(before_state, after_state, tool_call, execution_result, expectations):
    name = _expected_object_name(tool_call, execution_result, expectations)
    expected = expectations.get("solid_count", 1)
    obj = _get_object(after_state, name)
    topo = _get_attr(obj, "topology") if obj else None
    solids = _get_attr(topo, "solids", 0) if topo else 0
    return _result("verify_solid_count", solids == expected, "SOLID_COUNT_MISMATCH", f"Expected {expected} solids, got {solids}.")


def verify_bbox_close(before_state, after_state, tool_call, execution_result, expectations):
    name = _expected_object_name(tool_call, execution_result, expectations)
    expected = expectations.get("bbox") or _get_attr(tool_call.get("expected_effect", {}), "bbox")
    if not expected:
        return _result("verify_bbox_close", True, None, "No bbox expectation provided.")
    obj = _get_object(after_state, name)
    bbox = _bbox_dict(_get_attr(obj, "bbox") if obj else None)
    passed = bool(bbox) and all(isclose(float(bbox[k]), float(expected[k]), rel_tol=0.05, abs_tol=1.0) for k in expected if k in bbox)
    return _result("verify_bbox_close", passed, "BBOX_MISMATCH", f"Object '{name}' bbox is not close to expectation.")


def verify_bbox_center_close(before_state, after_state, tool_call, execution_result, expectations):
    name = _expected_object_name(tool_call, execution_result, expectations)
    expected = expectations.get("center")
    if not expected:
        return _result("verify_bbox_center_close", True, None, "No center expectation provided.")
    obj = _get_object(after_state, name)
    bbox = _get_attr(obj, "bbox") if obj else None
    center = _get_attr(bbox, "center", []) if bbox else []
    passed = len(center) == len(expected) and all(isclose(float(a), float(b), abs_tol=1.0) for a, b in zip(center, expected))
    return _result("verify_bbox_center_close", passed, "BBOX_CENTER_MISMATCH", f"Object '{name}' center is not close to expectation.")


def verify_volume_increased(before_state, after_state, tool_call, execution_result, expectations):
    return _verify_volume_delta("verify_volume_increased", before_state, after_state, tool_call, execution_result, increase=True)


def verify_volume_decreased(before_state, after_state, tool_call, execution_result, expectations):
    return _verify_volume_delta("verify_volume_decreased", before_state, after_state, tool_call, execution_result, increase=False)


def verify_source_hidden(before_state, after_state, tool_call, execution_result, expectations):
    sources = execution_result.get("source_objects") or []
    if not sources:
        source = tool_call.get("args", {}).get("target") or tool_call.get("args", {}).get("base")
        sources = [source] if source else []
    for source in sources:
        obj = _get_object(after_state, source)
        if obj is not None and bool(_get_attr(obj, "visible", True)):
            return _result("verify_source_hidden", False, "SOURCE_VISIBLE", f"Source object '{source}' is still visible.")
    return _result("verify_source_hidden", True, None, "Source objects are hidden or absent.")


def verify_no_unexpected_visible_objects(before_state, after_state, tool_call, execution_result, expectations):
    allowed = set(expectations.get("visible_objects", []))
    if not allowed:
        allowed.update(execution_result.get("produced_objects", []))
    visible = {obj.name if hasattr(obj, "name") else obj.get("name") for obj in _objects(after_state) if _get_attr(obj, "visible", True)}
    unexpected = visible - allowed if allowed else set()
    return _result("verify_no_unexpected_visible_objects", not unexpected, "UNEXPECTED_VISIBLE_OBJECT", f"Unexpected visible objects: {sorted(unexpected)}")


def verify_dependency_created(before_state, after_state, tool_call, execution_result, expectations):
    name = _expected_object_name(tool_call, execution_result, expectations)
    source = (execution_result.get("source_objects") or [None])[0]
    obj = _get_object(after_state, name)
    deps = _get_attr(obj, "dependencies") if obj else None
    out_list = _get_attr(deps, "out_list", []) if deps else []
    passed = bool(source and source in out_list)
    return _result("verify_dependency_created", passed, "DEPENDENCY_MISSING", f"Dependency from '{name}' to '{source}' was not found.")


def verify_attachment_gap(before_state, after_state, tool_call, execution_result, expectations):
    expected = expectations.get("attachment") or _get_attr(tool_call.get("expected_effect", {}), "attachment")
    if not expected:
        return _result(
            "verify_attachment_gap",
            False,
            "ATTACHMENT_EXPECTATION_MISSING",
            "No attachment expectation was provided.",
        )
    obj_a_name = expected.get("obj_a") or expected.get("target") or (execution_result.get("source_objects") or [None])[0]
    obj_b_name = expected.get("obj_b") or expected.get("object") or _expected_object_name(tool_call, execution_result, expectations)
    axis = str(expected.get("axis", "X")).upper()
    tolerance = float(expected.get("max_gap", expected.get("tolerance", 0.5)))
    obj_a = _get_object(after_state, obj_a_name)
    obj_b = _get_object(after_state, obj_b_name)
    if obj_a is None or obj_b is None:
        return _result(
            "verify_attachment_gap",
            False,
            "OBJECT_NOT_FOUND",
            f"Cannot measure attachment gap: '{obj_a_name}' or '{obj_b_name}' was not found.",
            expected={"obj_a": obj_a_name, "obj_b": obj_b_name, "axis": axis, "max_gap": tolerance},
        )
    measurement = _measure_bbox_gap(_get_attr(obj_a, "bbox"), _get_attr(obj_b, "bbox"), axis, tolerance)
    passed = measurement["gap"] <= tolerance
    repair_axis = axis.lower()
    repair_delta = -measurement["signed_distance"]
    return _result(
        "verify_attachment_gap",
        passed,
        "ATTACHMENT_GAP_TOO_LARGE",
        (
            f"{obj_b_name} gap to {obj_a_name} on {axis} is "
            f"{measurement['gap']:.3f}mm (tolerance {tolerance:.3f}mm)."
        ),
        expected={"gap": 0.0, "axis": axis, "max_gap": tolerance},
        actual=measurement,
        delta=measurement["signed_distance"],
        repair_hint=None if passed else {
            "tool": "move",
            "args": {
                "target": obj_b_name,
                f"d{repair_axis}": repair_delta,
            },
        },
    )


def verify_orientation(before_state, after_state, tool_call, execution_result, expectations):
    expected = expectations.get("orientation") or _get_attr(tool_call.get("expected_effect", {}), "orientation") or {}
    name = expected.get("object") or _expected_object_name(tool_call, execution_result, expectations)
    expected_axis = str(expected.get("expected_axis", expected.get("axis", "Z"))).upper()
    mode = expected.get("mode")
    obj = _get_object(after_state, name)
    if obj is None:
        return _result(
            "verify_orientation",
            False,
            "OBJECT_NOT_FOUND",
            f"Object '{name}' was not found.",
        )
    bbox = _get_attr(obj, "bbox")
    sizes = _bbox_sizes(bbox)
    if not sizes:
        return _result(
            "verify_orientation",
            False,
            "BBOX_MISSING",
            f"Object '{name}' has no bbox for orientation check.",
        )
    dominant_axis = max(sizes, key=sizes.get)
    thin_axis = min(sizes, key=sizes.get)
    if mode is None:
        obj_type = _get_attr(obj, "type", "")
        mode = "thin" if "Cylinder" in obj_type or "wheel" in name.lower() else "dominant"
    actual_axis = thin_axis if mode == "thin" else dominant_axis
    passed = actual_axis == expected_axis
    return _result(
        "verify_orientation",
        passed,
        "ORIENTATION_MISMATCH",
        f"Object '{name}' orientation axis is {actual_axis}, expected {expected_axis}.",
        expected={"axis": expected_axis, "mode": mode},
        actual={
            "actual_axis": actual_axis,
            "dominant_axis": dominant_axis,
            "thin_axis": thin_axis,
            "sizes": sizes,
        },
        repair_hint=None if passed else {
            "tool": "rotate",
            "args": {"target": name, "axis": "X", "angle": 90},
        },
    )


VALIDATORS = {
    "verify_object_exists": verify_object_exists,
    "verify_shape_valid": verify_shape_valid,
    "verify_solid_count": verify_solid_count,
    "verify_bbox_close": verify_bbox_close,
    "verify_bbox_center_close": verify_bbox_center_close,
    "verify_volume_increased": verify_volume_increased,
    "verify_volume_decreased": verify_volume_decreased,
    "verify_source_hidden": verify_source_hidden,
    "verify_no_unexpected_visible_objects": verify_no_unexpected_visible_objects,
    "verify_dependency_created": verify_dependency_created,
    "verify_attachment_gap": verify_attachment_gap,
    "verify_orientation": verify_orientation,
}


def _verify_volume_delta(name, before_state, after_state, tool_call, execution_result, *, increase: bool):
    before_name = (execution_result.get("source_objects") or [None])[0] or tool_call.get("args", {}).get("target")
    after_name = _expected_object_name(tool_call, execution_result, {})
    before_obj = _get_object(before_state, before_name)
    after_obj = _get_object(after_state, after_name)
    before_volume = _volume(before_obj)
    after_volume = _volume(after_obj)
    if before_volume is None or after_volume is None:
        return _result(name, False, "VOLUME_MISSING", "Before or after volume is missing.")
    passed = after_volume > before_volume if increase else after_volume < before_volume
    code = "VOLUME_NOT_INCREASED" if increase else "VOLUME_NOT_DECREASED"
    return _result(name, passed, code, f"Volume before={before_volume}, after={after_volume}.")


def _expected_object_name(tool_call, execution_result, expectations):
    if expectations.get("object"):
        return expectations["object"]
    produced = execution_result.get("produced_objects") or []
    if produced:
        return produced[0]
    expected = tool_call.get("expected_effect") or {}
    if expected.get("new_object"):
        return expected["new_object"]
    if expected.get("object"):
        return expected["object"]
    args = tool_call.get("args") or {}
    return (
        args.get("target")
        or args.get("sketch")
        or args.get("object")
        or args.get("base")
        or args.get("name")
    )


def _objects(state):
    if state is None:
        return []
    return state.objects if hasattr(state, "objects") else state.get("objects", [])


def _get_object(state, name):
    if not name:
        return None
    for obj in _objects(state):
        if _get_attr(obj, "name") == name:
            return obj
    return None


def _get_attr(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _volume(obj):
    topo = _get_attr(obj, "topology") if obj else None
    return _get_attr(topo, "volume") if topo else None


def _bbox_dict(bbox):
    if bbox is None:
        return {}
    if isinstance(bbox, dict):
        return bbox
    return {k: getattr(bbox, k) for k in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax") if hasattr(bbox, k)}


def _bbox_sizes(bbox):
    data = _bbox_dict(bbox)
    if data:
        return {
            "X": float(data["xmax"]) - float(data["xmin"]),
            "Y": float(data["ymax"]) - float(data["ymin"]),
            "Z": float(data["zmax"]) - float(data["zmin"]),
        }
    size = _get_attr(bbox, "size")
    if isinstance(size, list) and len(size) >= 3:
        return {"X": float(size[0]), "Y": float(size[1]), "Z": float(size[2])}
    return {}


def _measure_bbox_gap(bbox_a, bbox_b, axis: str, tolerance: float):
    a = _bbox_dict(bbox_a)
    b = _bbox_dict(bbox_b)
    axis = axis.upper()
    keys = {
        "X": ("xmin", "xmax"),
        "Y": ("ymin", "ymax"),
        "Z": ("zmin", "zmax"),
    }
    lo_key, hi_key = keys[axis]
    a_min, a_max = float(a[lo_key]), float(a[hi_key])
    b_min, b_max = float(b[lo_key]), float(b[hi_key])
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
        "touching": gap <= tolerance,
        "tolerance": tolerance,
    }


def _result(
    validator: str,
    passed: bool,
    error_code: str | None,
    message: str,
    **extras,
) -> dict:
    result = {
        "validator": validator,
        "passed": passed,
        "error_code": None if passed else error_code,
        "message": message,
    }
    result.update({k: v for k, v in extras.items() if v is not None})
    return result
