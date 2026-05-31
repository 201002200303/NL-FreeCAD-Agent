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
    return _result("verify_shape_valid", valid, "SHAPE_INVALID", f"Object '{name}' has invalid shape.")


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
    return expected.get("new_object") or expected.get("object")


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


def _result(validator: str, passed: bool, error_code: str | None, message: str) -> dict:
    return {
        "validator": validator,
        "passed": passed,
        "error_code": None if passed else error_code,
        "message": message,
    }

