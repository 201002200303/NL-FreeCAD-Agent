"""Tool call 清洗：保证满足 ToolCall schema（call_id 必填）。"""


def sanitize_tool_calls(calls: list | None, prefix: str = "repair") -> list[dict]:
    sanitized = []
    for i, call in enumerate(calls or []):
        if not isinstance(call, dict) or not call.get("tool"):
            continue
        sanitized.append({
            "call_id": call.get("call_id") or f"{prefix}_{i + 1}",
            "tool": call["tool"],
            "args": call.get("args") or {},
            "description": call.get("description") or "",
            "expected_effect": call.get("expected_effect"),
        })
    return sanitized
