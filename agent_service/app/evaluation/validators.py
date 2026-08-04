from math import isclose
from typing import Any

# 只有「对象根本没建出来」这两类才阻断推进；其余（贴合、朝向、尺寸偏差等）作为
# warning 回灌提示词，避免把主循环卡在几何微差上。
BLOCKING_VALIDATORS = {"verify_object_exists", "verify_shape_valid"}


def is_blocking_validator(result: dict) -> bool:
    return result.get("validator") in BLOCKING_VALIDATORS


def blocking_failures(validator_results: list[dict] | None) -> list[str]:
    """Failed blocking validators, formatted as `name:error_code`."""
    return [
        f"{item['validator']}:{item['error_code']}"
        for item in (validator_results or [])
        if not item.get("passed") and is_blocking_validator(item)
    ]


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


def verify_grounded(before_state, after_state, tool_call, execution_result, expectations):
    """Target bbox zmin should be near the ground plane (z=0)."""
    expected = expectations.get("grounded") or _get_attr(tool_call.get("expected_effect", {}), "grounded") or {}
    name = expected.get("object") or _expected_object_name(tool_call, execution_result, expectations)
    tolerance = float(expected.get("tolerance", expected.get("tol", 1.0)))
    obj = _get_object(after_state, name)
    if obj is None:
        return _result("verify_grounded", False, "OBJECT_NOT_FOUND", f"Object '{name}' was not found.")
    bbox = _bbox_dict(_get_attr(obj, "bbox"))
    if "zmin" not in bbox:
        return _result("verify_grounded", False, "BBOX_MISSING", f"Object '{name}' has no zmin.")
    zmin = float(bbox["zmin"])
    delta = zmin  # distance above ground; negative means below
    passed = abs(zmin) <= tolerance or (0 <= zmin <= tolerance)
    return _result(
        "verify_grounded",
        passed,
        "NOT_GROUNDED",
        f"Object '{name}' zmin={zmin:.3f}mm (tolerance {tolerance:.3f}mm).",
        expected={"zmin": 0.0, "tolerance": tolerance},
        actual={"zmin": zmin},
        delta=delta,
        repair_hint=None if passed else {
            "tool": "move",
            "args": {"target": name, "dz": -zmin},
        },
    )


def verify_no_overlap(before_state, after_state, tool_call, execution_result, expectations):
    """Fail when bbox overlap volume / min(volume) exceeds ratio (default 0.3)."""
    expected = expectations.get("no_overlap") or _get_attr(tool_call.get("expected_effect", {}), "no_overlap") or {}
    name_a = expected.get("obj_a") or expected.get("a")
    name_b = expected.get("obj_b") or expected.get("b") or _expected_object_name(tool_call, execution_result, expectations)
    if not name_a:
        sources = execution_result.get("source_objects") or []
        name_a = sources[0] if sources else (tool_call.get("args") or {}).get("base")
    max_ratio = float(expected.get("max_ratio", 0.3))
    obj_a = _get_object(after_state, name_a)
    obj_b = _get_object(after_state, name_b)
    if obj_a is None or obj_b is None:
        return _result(
            "verify_no_overlap",
            False,
            "OBJECT_NOT_FOUND",
            f"Cannot check overlap: '{name_a}' or '{name_b}' missing.",
        )
    a = _bbox_dict(_get_attr(obj_a, "bbox"))
    b = _bbox_dict(_get_attr(obj_b, "bbox"))
    try:
        ox = max(0.0, min(float(a["xmax"]), float(b["xmax"])) - max(float(a["xmin"]), float(b["xmin"])))
        oy = max(0.0, min(float(a["ymax"]), float(b["ymax"])) - max(float(a["ymin"]), float(b["ymin"])))
        oz = max(0.0, min(float(a["zmax"]), float(b["zmax"])) - max(float(a["zmin"]), float(b["zmin"])))
    except (KeyError, TypeError, ValueError):
        return _result("verify_no_overlap", False, "BBOX_MISSING", "Missing bbox bounds for overlap check.")
    overlap_vol = ox * oy * oz
    vol_a = max(1e-9, (float(a["xmax"]) - float(a["xmin"])) * (float(a["ymax"]) - float(a["ymin"])) * (float(a["zmax"]) - float(a["zmin"])))
    vol_b = max(1e-9, (float(b["xmax"]) - float(b["xmin"])) * (float(b["ymax"]) - float(b["ymin"])) * (float(b["zmax"]) - float(b["zmin"])))
    ratio = overlap_vol / min(vol_a, vol_b)
    passed = ratio <= max_ratio
    # Repair: push along the axis with smallest overlap extent
    axes = [("x", ox), ("y", oy), ("z", oz)]
    axis, extent = min(axes, key=lambda t: t[1] if t[1] > 0 else 1e9)
    sign = 1.0
    if axis == "x":
        sign = 1.0 if float(b["xmin"]) >= float(a["xmin"]) else -1.0
    elif axis == "y":
        sign = 1.0 if float(b["ymin"]) >= float(a["ymin"]) else -1.0
    else:
        sign = 1.0 if float(b["zmin"]) >= float(a["zmin"]) else -1.0
    return _result(
        "verify_no_overlap",
        passed,
        "BBOX_OVERLAP_TOO_LARGE",
        f"{name_a} and {name_b} bbox overlap ratio={ratio:.3f} (max {max_ratio}).",
        expected={"max_ratio": max_ratio},
        actual={"overlap_volume": overlap_vol, "ratio": ratio, "extents": {"x": ox, "y": oy, "z": oz}},
        delta=ratio - max_ratio,
        repair_hint=None if passed else {
            "tool": "move",
            "args": {"target": name_b, f"d{axis}": sign * (extent + 0.1)},
        },
    )


def verify_touching(before_state, after_state, tool_call, execution_result, expectations):
    """Two objects should nearly touch on an axis (gap <= tol)."""
    expected = expectations.get("touching") or _get_attr(tool_call.get("expected_effect", {}), "touching") or {}
    name_a = expected.get("obj_a") or expected.get("a")
    name_b = expected.get("obj_b") or expected.get("b") or _expected_object_name(tool_call, execution_result, expectations)
    if not name_a:
        name_a = (execution_result.get("source_objects") or [None])[0] or (tool_call.get("args") or {}).get("base")
    axis = str(expected.get("axis", "X")).upper()
    tolerance = float(expected.get("tolerance", expected.get("tol", 0.5)))
    obj_a = _get_object(after_state, name_a)
    obj_b = _get_object(after_state, name_b)
    if obj_a is None or obj_b is None:
        return _result(
            "verify_touching",
            False,
            "OBJECT_NOT_FOUND",
            f"Cannot measure touch: '{name_a}' or '{name_b}' missing.",
        )
    measurement = _measure_bbox_gap(_get_attr(obj_a, "bbox"), _get_attr(obj_b, "bbox"), axis, tolerance)
    passed = measurement["gap"] <= tolerance
    repair_axis = axis.lower()
    repair_delta = -measurement["signed_distance"]
    return _result(
        "verify_touching",
        passed,
        "NOT_TOUCHING",
        f"{name_b} gap to {name_a} on {axis} is {measurement['gap']:.3f}mm (tol {tolerance:.3f}mm).",
        expected={"gap": 0.0, "axis": axis, "tolerance": tolerance},
        actual=measurement,
        delta=measurement["signed_distance"],
        repair_hint=None if passed else {
            "tool": "move",
            "args": {"target": name_b, f"d{repair_axis}": repair_delta},
        },
    )


def verify_size_close(before_state, after_state, tool_call, execution_result, expectations):
    """bbox size within tol_ratio of expected_size [sx,sy,sz]."""
    expected = expectations.get("size") or _get_attr(tool_call.get("expected_effect", {}), "size") or {}
    if isinstance(expected, list):
        expected = {"expected_size": expected}
    name = expected.get("object") or _expected_object_name(tool_call, execution_result, expectations)
    expected_size = expected.get("expected_size") or expected.get("size")
    tol_ratio = float(expected.get("tol_ratio", 0.15))
    if not expected_size or len(expected_size) < 3:
        return _result(
            "verify_size_close",
            False,
            "SIZE_EXPECTATION_MISSING",
            "expected_size [sx,sy,sz] is required.",
        )
    obj = _get_object(after_state, name)
    if obj is None:
        return _result("verify_size_close", False, "OBJECT_NOT_FOUND", f"Object '{name}' was not found.")
    bbox = _bbox_dict(_get_attr(obj, "bbox"))
    size = bbox.get("size")
    if not size:
        sizes = _bbox_sizes(bbox)
        if not sizes:
            return _result("verify_size_close", False, "BBOX_MISSING", f"Object '{name}' has no size.")
        size = [sizes["X"], sizes["Y"], sizes["Z"]]
    actual = [float(size[0]), float(size[1]), float(size[2])]
    exp = [float(expected_size[0]), float(expected_size[1]), float(expected_size[2])]
    ratios = []
    for a, e in zip(actual, exp):
        if abs(e) < 1e-9:
            ratios.append(0.0 if abs(a) < 1e-9 else 1.0)
        else:
            ratios.append(abs(a - e) / abs(e))
    max_err = max(ratios) if ratios else 1.0
    passed = max_err <= tol_ratio
    return _result(
        "verify_size_close",
        passed,
        "SIZE_MISMATCH",
        f"Object '{name}' size={actual} expected={exp} max_err={max_err:.3f} (tol_ratio={tol_ratio}).",
        expected={"size": exp, "tol_ratio": tol_ratio},
        actual={"size": actual, "max_err": max_err},
        delta=max_err,
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
    "verify_grounded": verify_grounded,
    "verify_no_overlap": verify_no_overlap,
    "verify_touching": verify_touching,
    "verify_size_close": verify_size_close,
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
