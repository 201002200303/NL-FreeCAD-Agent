"""Pure geometry-oracle logic: no FreeCAD import.

Cases declare what they expect from a tool call; the runner reads real Shape
facts from FreeCAD and this module decides pass/fail.  Keeping expectations and
comparison FreeCAD-free lets the case table be validated in normal CI.
"""

from __future__ import annotations

TOL = 0.5

EXPECT_KINDS = frozenset(
    {"bbox_size", "bbox_center", "solids", "volume_range", "axis_along", "valid"}
)

LAYERS = frozenset({"L3", "L4"})


_SYMMETRY_TOL = 0.01


def axis_from_symmetry(size) -> str | None:
    """Rotational axis of a revolved solid from its bbox.

    A cylinder/cone/torus bbox has two equal dimensions; the axis is the third.
    Returns None when the shape is axis-ambiguous (cube/sphere) or not
    revolution-symmetric.
    """
    try:
        values = [float(v) for v in size]
    except (TypeError, ValueError):
        return None
    if len(values) != 3:
        return None

    # (pair, remaining axis index): the equal pair identifies the axis.
    pairs = [((0, 1), 2), ((0, 2), 1), ((1, 2), 0)]
    diffs = [(abs(values[a] - values[b]), axis) for (a, b), axis in pairs]
    best_diff, best_axis = min(diffs)
    if best_diff > _SYMMETRY_TOL:
        return None
    others = [d for d, axis in diffs if axis != best_axis]
    if others and max(others) <= _SYMMETRY_TOL:
        return None
    return "XYZ"[best_axis]


def _close_vector(actual, expected, tol: float) -> bool:
    try:
        a = [float(v) for v in actual]
        e = [float(v) for v in expected]
    except (TypeError, ValueError):
        return False
    if len(a) != len(e):
        return False
    return all(abs(x - y) <= tol for x, y in zip(a, e))


def evaluate_facts(facts: dict, expect: dict, *, tol: float = TOL) -> list[dict]:
    """Compare observed Shape facts against a case's expectations."""
    results: list[dict] = []
    for kind, wanted in (expect or {}).items():
        actual = None
        passed = False

        if kind == "bbox_size":
            actual = facts.get("bbox_size")
            passed = _close_vector(actual, wanted, tol)
        elif kind == "bbox_center":
            actual = facts.get("bbox_center")
            passed = _close_vector(actual, wanted, tol)
        elif kind == "solids":
            actual = facts.get("solids")
            passed = actual == wanted
        elif kind == "valid":
            actual = facts.get("valid")
            passed = actual is wanted
        elif kind == "volume_range":
            actual = facts.get("volume")
            try:
                lo, hi = float(wanted[0]), float(wanted[1])
                passed = lo <= float(actual) <= hi
            except (TypeError, ValueError, IndexError):
                passed = False
        elif kind == "axis_along":
            actual = axis_from_symmetry(facts.get("bbox_size") or [])
            passed = str(actual or "").upper() == str(wanted or "").upper()
        else:
            actual = "unsupported"

        results.append(
            {"kind": kind, "passed": bool(passed), "expected": wanted, "actual": actual}
        )
    return results


def validate_cases(cases: list[dict]) -> list[str]:
    """Static schema check for the case table; returns human-readable errors."""
    errors: list[str] = []
    seen: set[str] = set()

    for index, case in enumerate(cases or []):
        where = case.get("id") if isinstance(case, dict) else f"#{index}"
        if not isinstance(case, dict):
            errors.append(f"{where}: case must be a dict")
            continue

        case_id = str(case.get("id") or "").strip()
        if not case_id:
            errors.append(f"{where}: missing id")
        elif case_id in seen:
            errors.append(f"{case_id}: duplicate id")
        else:
            seen.add(case_id)

        layer = str(case.get("layer") or "")
        if layer not in LAYERS:
            errors.append(f"{where}: layer must be L3 or L4, got {layer!r}")

        if layer == "L4":
            if not str(case.get("code") or "").strip():
                errors.append(f"{where}: L4 case needs code")
        elif layer == "L3":
            if not str(case.get("tool") or "").strip():
                errors.append(f"{where}: L3 case needs tool")
            if not isinstance(case.get("args"), dict):
                errors.append(f"{where}: L3 case needs args dict")

        expect = case.get("expect")
        if not isinstance(expect, dict) or not expect:
            errors.append(f"{where}: expect must be a non-empty dict")
        else:
            unknown = sorted(set(expect) - EXPECT_KINDS)
            if unknown:
                errors.append(f"{where}: unknown expectation kinds {unknown}")

        if not str(case.get("ref") or "").strip():
            errors.append(f"{where}: missing ref (must cite FreeCAD behavior)")

    return errors
