"""Capability handshake policy: when may the client refuse to model?

The agent and the FreeCAD add-on are separate installs, so the client checks the
server's cad_api_version before executing programmes.  A missing answer is not
evidence of drift — only an explicitly different version is.
"""
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "freecad_addon"))

from AICADAgent.capabilities import evaluate_cad_api_compatibility  # noqa: E402


def test_matching_version_is_not_blocked():
    blocked, reason = evaluate_cad_api_compatibility("1.1", "1.1")
    assert blocked is False
    assert reason == ""


def test_unknown_remote_version_fails_open():
    """服务端没答/答不上时不能阻断建模。"""
    for remote in (None, "", "   "):
        blocked, reason = evaluate_cad_api_compatibility(remote, "1.1")
        assert blocked is False, remote
        assert reason == ""


def test_missing_local_version_fails_open():
    blocked, _ = evaluate_cad_api_compatibility("1.1", "")
    assert blocked is False


def test_confirmed_mismatch_blocks_and_explains():
    blocked, reason = evaluate_cad_api_compatibility("1.0", "1.1")
    assert blocked is True
    assert "1.1" in reason and "1.0" in reason


def _runner_source() -> str:
    return (
        REPO_ROOT / "freecad_addon" / "AICADAgent" / "agent_runner.py"
    ).read_text(encoding="utf-8")


def test_execution_gate_blocks_only_on_confirmed_mismatch():
    source = _runner_source()
    assert "if self._cad_api_compatible is False:" in source
    assert "if self._cad_api_compatible is not True:" not in source


def test_probe_failure_keeps_unknown_and_schedules_retry():
    source = _runner_source()
    assert self_fail_open_marker() in source
    assert "_schedule_capabilities_retry" in source


def self_fail_open_marker() -> str:
    return "self._cad_api_compatible = None"
