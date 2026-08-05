"""execute_cad_program 受限源码 AST 校验（服务端权威）。"""

from app.cad_program.validate import validate_cad_source


def test_valid_program_passes():
    code = """
torso = cad.box(name="Torso", size=(40, 25, 55), center=(0, 0, 120))
pelvis = cad.box(name="Pelvis", size=(35, 22, 20), center=(0, 0, 80))
for side in (-1, 1):
    cad.sphere(name=f"Shoulder_{side}", radius=8, center=(side * 30, 0, 135))
"""
    verdict = validate_cad_source(code)
    assert verdict.ok is True
    assert verdict.violations == []


def test_import_is_forbidden():
    verdict = validate_cad_source("import os\nx = 1")
    assert verdict.ok is False
    assert any(v["kind"] == "forbidden" for v in verdict.violations)


def test_dunder_and_attribute_escape_forbidden():
    for code in (
        "x = cad.__dict__",
        "x = ().__class__",
        "x = getattr(cad, 'box')",
    ):
        verdict = validate_cad_source(code)
        assert verdict.ok is False, code


def test_unknown_cad_method_rejected():
    verdict = validate_cad_source('cad.launch_missile(name="X")')
    assert verdict.ok is False
    assert any("unknown" in v["kind"] or "forbidden" in v["kind"] for v in verdict.violations)


def test_syntax_error_reported():
    verdict = validate_cad_source("def broken(:\n")
    assert verdict.ok is False
    assert any(v["kind"] == "syntax_error" for v in verdict.violations)


def test_resource_limit_loop_and_calls():
    code = "\n".join(f'cad.box(name="b{i}", size=(1,1,1), center=(0,0,0))' for i in range(600))
    verdict = validate_cad_source(code)
    assert verdict.ok is False
    assert any(v["kind"] == "resource_limit" for v in verdict.violations)
