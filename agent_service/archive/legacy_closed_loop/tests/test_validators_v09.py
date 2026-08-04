"""V0.9 hard geometry validators (dict fixtures, no FreeCAD)."""

from app.evaluation.validators import (
    verify_grounded,
    verify_no_overlap,
    verify_touching,
    verify_size_close,
)


def _obj(name, xmin, xmax, ymin, ymax, zmin, zmax):
    return {
        "name": name,
        "type": "Part::Box",
        "bbox": {
            "xmin": xmin,
            "xmax": xmax,
            "ymin": ymin,
            "ymax": ymax,
            "zmin": zmin,
            "zmax": zmax,
            "size": [xmax - xmin, ymax - ymin, zmax - zmin],
            "center": [(xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2],
        },
    }


def test_verify_grounded_floating():
    after = {"objects": [_obj("Box", 0, 10, 0, 10, 5, 15)]}
    result = verify_grounded(
        None,
        after,
        {"args": {"target": "Box"}, "expected_effect": {"grounded": {"tolerance": 1.0}}},
        {"produced_objects": ["Box"]},
        {},
    )
    assert result["passed"] is False
    assert abs(result["delta"] - 5.0) < 1e-6
    assert result["repair_hint"]["args"]["dz"] == -5.0


def test_verify_grounded_ok():
    after = {"objects": [_obj("Box", 0, 10, 0, 10, 0, 10)]}
    result = verify_grounded(
        None,
        after,
        {"args": {"name": "Box"}},
        {"produced_objects": ["Box"]},
        {},
    )
    assert result["passed"] is True


def test_verify_no_overlap_fails():
    after = {
        "objects": [
            _obj("A", 0, 10, 0, 10, 0, 10),
            _obj("B", 5, 15, 0, 10, 0, 10),  # overlaps on X
        ]
    }
    result = verify_no_overlap(
        None,
        after,
        {"expected_effect": {"no_overlap": {"obj_a": "A", "obj_b": "B", "max_ratio": 0.3}}},
        {},
        {},
    )
    assert result["passed"] is False
    assert result["repair_hint"]["tool"] == "move"
    assert "dx" in result["repair_hint"]["args"]


def test_verify_touching_gap():
    after = {
        "objects": [
            _obj("A", 0, 10, 0, 10, 0, 10),
            _obj("B", 13, 23, 0, 10, 0, 10),  # gap 3 on X
        ]
    }
    result = verify_touching(
        None,
        after,
        {"expected_effect": {"touching": {"obj_a": "A", "obj_b": "B", "axis": "X", "tolerance": 0.5}}},
        {},
        {},
    )
    assert result["passed"] is False
    assert abs(result["actual"]["gap"] - 3.0) < 1e-6
    assert abs(result["repair_hint"]["args"]["dx"] - (-3.0)) < 1e-6


def test_verify_size_close_mismatch():
    after = {"objects": [_obj("Box", 0, 100, 0, 60, 0, 20)]}
    result = verify_size_close(
        None,
        after,
        {
            "expected_effect": {
                "size": {"object": "Box", "expected_size": [100, 60, 40], "tol_ratio": 0.15}
            }
        },
        {"produced_objects": ["Box"]},
        {},
    )
    assert result["passed"] is False
    assert result["error_code"] == "SIZE_MISMATCH"
