"""Deterministic acceptance checks over a DocumentState snapshot."""

from __future__ import annotations

from typing import Any, Optional


def _as_dict(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return {}


def normalize_acceptance(value: Any) -> list[dict]:
    """Keep only structured checks; prose remains useful to the Agent, not the gate."""
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict) and item.get("type")]


def _objects(document_state: Any) -> dict[str, dict]:
    state = _as_dict(document_state)
    return {
        str(obj.get("name")): obj
        for obj in (state.get("objects") or [])
        if isinstance(obj, dict) and obj.get("name")
    }


def _close_vector(actual: Any, expected: Any, tolerance: float) -> bool:
    try:
        a = [float(v) for v in actual]
        e = [float(v) for v in expected]
        return len(a) == len(e) and all(abs(x - y) <= tolerance for x, y in zip(a, e))
    except (TypeError, ValueError):
        return False


def evaluate_acceptance(
    checks: list[dict],
    document_state: Any,
    *,
    state_diff: Optional[dict] = None,
) -> list[dict]:
    """Evaluate the supported acceptance vocabulary without calling an LLM."""
    objects = _objects(document_state)
    results: list[dict] = []
    for raw in checks:
        check = dict(raw)
        kind = str(check.get("type") or "")
        target = str(check.get("target") or "")
        obj = objects.get(target)
        actual: Any = None
        passed = False

        if kind == "object_exists":
            actual = obj is not None
            passed = actual
        elif kind == "object_absent":
            actual = obj is None
            passed = actual
        elif kind == "valid_shape":
            actual = ((obj or {}).get("topology") or {}).get("is_valid")
            passed = actual is True
        elif kind == "solid_count":
            actual = ((obj or {}).get("topology") or {}).get("solids")
            passed = actual == check.get("equals")
        elif kind == "bbox_size":
            actual = ((obj or {}).get("bbox") or {}).get("size")
            passed = _close_vector(actual, check.get("value"), float(check.get("tolerance", 0.1)))
        elif kind == "bbox_center":
            actual = ((obj or {}).get("bbox") or {}).get("center")
            passed = _close_vector(actual, check.get("value"), float(check.get("tolerance", 0.1)))
        elif kind == "volume_range":
            actual = ((obj or {}).get("topology") or {}).get("volume")
            try:
                value = float(actual)
                passed = float(check.get("min", float("-inf"))) <= value <= float(
                    check.get("max", float("inf"))
                )
            except (TypeError, ValueError):
                passed = False
        elif kind == "object_count":
            actual = len(objects)
            minimum = int(check.get("min", actual))
            maximum = int(check.get("max", actual))
            expected = check.get("equals")
            passed = actual == int(expected) if expected is not None else minimum <= actual <= maximum
        elif kind == "document_changed":
            actual = bool((state_diff or {}).get("changed"))
            passed = actual
        else:
            actual = "unsupported"
            passed = False

        results.append({**check, "passed": bool(passed), "actual": actual})
    return results

