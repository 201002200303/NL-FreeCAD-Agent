"""Deterministic execution gate for step evaluation.

Default policy is deliberately light: a step is blocked only when the tool did
not run successfully. Geometry/object checks belong to optional strict/debug
validation, not the main loop.
"""


def run_deterministic_checks(
    last_tool_call: dict,
    execution_result: dict,
    document_state,
) -> dict:
    """Return whether tool execution itself succeeded."""
    status = execution_result.get("status", "")

    if status == "error":
        msg = execution_result.get("message", "Unknown tool execution error")
        return {
            "passed": False,
            "issues": [f"tool_execution_failed: {msg}"],
            "suggested_decision": "repair",
        }

    if status != "success":
        return {
            "passed": False,
            "issues": [f"tool_execution_status_unknown: {status}"],
            "suggested_decision": "skip_and_continue",
        }

    return {
        "passed": True,
        "issues": [],
        "suggested_decision": "continue",
    }
