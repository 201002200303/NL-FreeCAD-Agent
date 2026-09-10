import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "freecad_addon"))

from app.cad_program.manifest import CAD_API_METHODS, CAD_TO_TOOL
from app.cad_program.validate import validate_cad_source
from app.tools.tool_specs import TOOL_SPECS
from AICADAgent.cad_program.manifest import CAD_API_METHODS as PLUGIN_METHODS
from AICADAgent.cad_program.manifest import CAD_TO_TOOL as PLUGIN_CAD_TO_TOOL


def test_every_model_visible_operation_has_runtime_and_tool_contract():
    assert CAD_API_METHODS == frozenset(CAD_TO_TOOL)
    assert PLUGIN_METHODS == CAD_API_METHODS
    assert PLUGIN_CAD_TO_TOOL == CAD_TO_TOOL
    assert set(CAD_TO_TOOL.values()) <= set(TOOL_SPECS)
    for method in CAD_API_METHODS:
        verdict = validate_cad_source(f"cad.{method}()")
        assert verdict.ok, (method, verdict.violations)


def test_removed_query_placeholders_are_rejected_in_preflight():
    for method in ("get", "document", "validate", "measure"):
        verdict = validate_cad_source(f"cad.{method}()")
        assert not verdict.ok, method
