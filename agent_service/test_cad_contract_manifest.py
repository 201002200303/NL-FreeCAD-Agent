import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "freecad_addon"))

from app.cad_program import manifest as manifest_mod
from app.cad_program.manifest import CAD_API_METHODS, CAD_API_VERSION, CAD_TO_TOOL
from app.cad_program.validate import validate_cad_source
from app.tools.tool_specs import TOOL_SPECS
from AICADAgent.cad_program import manifest as plugin_manifest_mod
from AICADAgent.cad_program.manifest import CAD_API_METHODS as PLUGIN_METHODS
from AICADAgent.cad_program.manifest import CAD_TO_TOOL as PLUGIN_CAD_TO_TOOL

PLUGIN_MANIFEST_PATH = REPO_ROOT / "freecad_addon" / "AICADAgent" / "cad_program" / "manifest.py"


def _load_sync_script():
    path = REPO_ROOT / "scripts" / "sync_cad_manifest.py"
    spec = importlib.util.spec_from_file_location("_sync_cad_manifest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_cad_api_version_is_released_and_matches_plugin():
    """版本号不带 -test 后缀，否则任何版本差分都会误判不兼容。"""
    assert CAD_API_VERSION == "1.2"
    assert plugin_manifest_mod.CAD_API_VERSION == CAD_API_VERSION


def test_experimental_apis_are_not_model_visible():
    """wedge/sweep 未经几何验收，不进模型可见目录（工具本身保留）。"""
    assert "wedge" not in CAD_TO_TOOL
    assert "sweep" not in CAD_TO_TOOL
    assert not hasattr(manifest_mod, "CAD_API_TEST")
    for method in ("wedge", "sweep"):
        assert not validate_cad_source(f"cad.{method}()").ok, method
    assert validate_cad_source("cad.loft()").ok  # 稳定 API 不受影响
    assert "create_wedge" in TOOL_SPECS and "make_sweep" in TOOL_SPECS


def test_plugin_manifest_is_generated_from_canonical_copy():
    """插件副本必须由 canonical 生成，禁止手工维护出第二份真源。"""
    sync = _load_sync_script()
    assert sync.check() == []
    assert PLUGIN_MANIFEST_PATH.read_text(encoding="utf-8").replace(
        "\r\n", "\n"
    ) == sync.expected_plugin_source().replace("\r\n", "\n")


def test_sync_check_detects_drift(tmp_path, monkeypatch):
    sync = _load_sync_script()
    drifted = tmp_path / "manifest.py"
    drifted.write_text("# hand-edited\n", encoding="utf-8")
    monkeypatch.setattr(sync, "PLUGIN", drifted)
    errors = sync.check()
    assert errors and "out of sync" in errors[0]


def test_plugin_executor_hot_reloads_manifest():
    """manifest 不热加载时，磁盘改了 cad 契约仍用启动时旧副本。"""
    source = (REPO_ROOT / "freecad_addon" / "AICADAgent" / "executor.py").read_text(
        encoding="utf-8"
    )
    assert "import AICADAgent.cad_program.manifest as _cad_manifest" in source
    assert "importlib.reload(_cad_manifest)" in source
