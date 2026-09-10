"""FreeCAD-free gate for the geometry oracle.

Validates the case table schema and the comparison logic so that a bad case
(re-baselined expectation, typo in an expectation kind, AST-invalid program)
fails in normal CI.  Real geometry still requires FreeCADCmd via runner.py.
"""
import importlib.util
from pathlib import Path

from app.cad_program.validate import validate_cad_source

ORACLE_DIR = (
    Path(__file__).resolve().parent.parent
    / "freecad_addon"
    / "AICADAgent"
    / "tests"
    / "geometry_oracle"
)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_geo_oracle_{name}", ORACLE_DIR / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


oracle = _load("oracle")
cases_mod = _load("cases")


def test_oracle_module_exists():
    assert (ORACLE_DIR / "runner.py").is_file()


def test_case_table_is_schema_valid():
    assert oracle.validate_cases(cases_mod.CASES) == []


def test_validate_cases_reports_problems():
    errors = oracle.validate_cases(
        [
            {"id": "dup", "layer": "L4", "code": "pass", "expect": {"solids": 1}, "ref": "x"},
            {
                "id": "dup",
                "layer": "L9",
                "expect": {"nope": 1},
            },
        ]
    )
    assert any("duplicate" in err for err in errors)
    assert any("layer" in err for err in errors)
    assert any("unknown expectation" in err for err in errors)
    assert any("missing ref" in err for err in errors)


def test_every_l4_case_passes_the_ast_sandbox():
    for case in cases_mod.CASES:
        if case["layer"] != "L4":
            continue
        verdict = validate_cad_source(case["code"])
        assert verdict.ok, (case["id"], verdict.violations)


def test_case_table_covers_high_risk_families():
    ids = " ".join(case["id"] for case in cases_mod.CASES)
    for family in (
        "box",
        "cylinder",
        "cone",
        "rotate",
        "hole",
        "fuse",
        "cut",
        "polar_pattern",
        "linear_pattern",
        "extrude",
        "torus",
    ):
        assert family in ids, f"missing oracle coverage for {family}"


def test_axis_from_symmetry():
    assert oracle.axis_from_symmetry([20, 20, 30]) == "Z"  # tall cylinder
    assert oracle.axis_from_symmetry([50, 50, 10]) == "Z"  # flat disc/torus
    assert oracle.axis_from_symmetry([8, 40, 40]) == "X"
    assert oracle.axis_from_symmetry([30, 6, 30]) == "Y"
    assert oracle.axis_from_symmetry([10, 10, 10]) is None  # cube is ambiguous
    assert oracle.axis_from_symmetry([4, 9, 17]) is None  # not a revolved solid


def test_evaluate_facts_accepts_correct_facts_and_tolerates_float_noise():
    checks = oracle.evaluate_facts(
        {"bbox_size": [40.3, 20.0, 10.0], "bbox_center": [0, 0, 5], "solids": 1},
        {"bbox_size": [40, 20, 10], "bbox_center": [0, 0, 5], "solids": 1},
    )
    assert all(check["passed"] for check in checks)


def test_evaluate_facts_rejects_wrong_axis_and_size():
    # 实测是竖直圆柱（轴 Z），用例期望侧向圆柱（轴 X）——两者都必须判失败
    checks = oracle.evaluate_facts(
        {"bbox_size": [20, 20, 30]},
        {"bbox_size": [8, 40, 40], "axis_along": "X"},
    )
    by_kind = {check["kind"]: check for check in checks}
    assert by_kind["bbox_size"]["passed"] is False
    assert by_kind["axis_along"]["passed"] is False


def test_evaluate_facts_matches_axis_when_correct():
    checks = oracle.evaluate_facts(
        {"bbox_size": [8, 40, 40]}, {"axis_along": "X"}
    )
    assert checks[0]["passed"] is True


def test_evaluate_facts_volume_range():
    assert oracle.evaluate_facts({"volume": 6429.0}, {"volume_range": [6350, 6500]})[0][
        "passed"
    ]
    assert not oracle.evaluate_facts({"volume": 8000.0}, {"volume_range": [6350, 6500]})[0][
        "passed"
    ]
