"""Schema-only replay for V0.8 trace folders."""

from __future__ import annotations

import json
from pathlib import Path


LEGAL_NEXT_DECISIONS = {"execute", "ask_user", "repair", "replan", "finish", "abort"}
LEGAL_EVAL_DECISIONS = {"continue", "repair", "skip_and_continue", "replan", "finish", "abort"}


def replay_trace(trace_dir: str | Path) -> dict:
    root = Path(trace_dir)
    issues: list[str] = []
    if not root.exists():
        return {"status": "error", "issues": [f"Trace folder not found: {root}"]}

    summary_path = root / "session_summary.json"
    if not summary_path.exists():
        issues.append("Missing session_summary.json")
        return {"status": "error", "issues": issues}

    summary = _read_json(summary_path, issues)
    for step in summary.get("steps", []):
        step_name = step.get("step_name")
        endpoint = step.get("endpoint")
        step_dir = root / step_name
        if not step_dir.exists():
            issues.append(f"Missing step folder: {step_name}")
            continue
        response = _read_json(step_dir / "api_response.json", issues, optional=True)
        if response:
            _validate_decision(endpoint, response, issues)
        _validate_executions(step_dir, issues)

    return {"status": "ok" if not issues else "error", "issues": issues}


def _validate_decision(endpoint: str, response: dict, issues: list[str]) -> None:
    if endpoint == "next_step":
        decision = response.get("decision")
        if decision not in LEGAL_NEXT_DECISIONS:
            issues.append(f"Invalid next_step decision: {decision}")
        for call in response.get("tool_calls", []):
            if not call.get("call_id"):
                issues.append("next_step tool_call missing call_id")
    if endpoint == "evaluate_step":
        decision = response.get("decision")
        if decision not in LEGAL_EVAL_DECISIONS:
            issues.append(f"Invalid evaluate_step decision: {decision}")
        has_harness_context = bool(response.get("current_abstract_step") or response.get("abstract_step_queue"))
        if (
            decision in {"continue", "finish"}
            and has_harness_context
            and response.get("validator_results") == []
            and response.get("abstract_step_completed") is False
        ):
            issues.append("evaluate_step harness path missing validator results")


def _validate_executions(step_dir: Path, issues: list[str]) -> None:
    exec_dir = step_dir / "executions"
    if not exec_dir.exists():
        return
    for tool_call_path in exec_dir.glob("*_tool_call.json"):
        data = _read_json(tool_call_path, issues)
        if data and not data.get("call_id"):
            issues.append(f"Execution tool call missing call_id: {tool_call_path.name}")


def _read_json(path: Path, issues: list[str], optional: bool = False):
    if not path.exists():
        if not optional:
            issues.append(f"Missing file: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(f"Invalid JSON {path}: {exc}")
        return None


if __name__ == "__main__":
    import sys

    result = replay_trace(sys.argv[1] if len(sys.argv) > 1 else ".")
    print(json.dumps(result, ensure_ascii=False, indent=2))
