"""Query-before-act policy for spatially risky CAD tool calls."""

QUERY_TOOLS = {
    "summarize_document",
    "get_object_detail",
    "measure_gap",
    "compare_orientation",
    "list_topology",
}

RISKY_TOOLS = {
    "set_placement",
    "move",
    "rotate",
    "add_fillet",
    "add_chamfer",
    "boolean_cut",
    "boolean_fuse",
    "boolean_common",
    "cut_hole",
    "create_sketch_on_face",
    "pad_to_face",
}

QUERY_BY_TOOL = {
    "add_fillet": "list_topology",
    "add_chamfer": "list_topology",
    "create_sketch_on_face": "list_topology",
    "pad_to_face": "list_topology",
    "set_placement": "get_object_detail",
    "move": "get_object_detail",
    "rotate": "get_object_detail",
    "cut_hole": "get_object_detail",
    "boolean_cut": "get_object_detail",
    "boolean_fuse": "get_object_detail",
    "boolean_common": "get_object_detail",
}

TARGET_FIELDS = (
    "target",
    "base",
    "tool",
    "obj_a",
    "obj_b",
    "part1",
    "part2",
)


def is_query_tool(tool_name: str) -> bool:
    return tool_name in QUERY_TOOLS


def extract_target_from_call(call: dict) -> str | None:
    args = call.get("args") or {}
    for field in TARGET_FIELDS:
        value = args.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def validate_query_before_act(
    tool_calls: list[dict],
    execution_history: dict | None,
    session_memory: dict | None = None,
) -> list[dict]:
    errors: list[dict] = []
    for call in tool_calls:
        tool = call.get("tool")
        if not tool or is_query_tool(tool):
            continue
        target = extract_target_from_call(call)
        if not target:
            continue
        if not _is_risky_call(call):
            continue
        if query_cache_covers_target(session_memory or {}, target):
            continue
        if recent_query_covers_target(execution_history or {}, target):
            continue
        errors.append({
            "error_code": "QUERY_REQUIRED",
            "tool": tool,
            "target": target,
            "required_query": "get_object_detail, measure_gap, compare_orientation, or list_topology",
            "reason": "空间/拓扑相关操作需要先查询当前几何事实。",
        })
    return errors


def build_required_query_calls(query_errors: list[dict]) -> list[dict]:
    calls: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for idx, error in enumerate(query_errors, start=1):
        target = error.get("target")
        if not target:
            continue
        tool = _query_tool_for_error(error)
        key = (tool, target)
        if key in seen:
            continue
        seen.add(key)
        calls.append({
            "call_id": f"query_required_{idx}",
            "tool": tool,
            "args": {"target": target},
            "description": f"补充 {target} 的当前几何事实后再执行 {error.get('tool')}",
            "expected_effect": {
                "kind": "query",
                "query_target": target,
                "reason": error.get("reason"),
            },
        })
    return calls


def query_cache_covers_target(session_memory: dict, target: str) -> bool:
    target = target.strip()
    if not target or not session_memory:
        return False
    query_cache = session_memory.get("query_cache") or {}
    if target in query_cache:
        return True
    full_cache = session_memory.get("_query_cache_full") or {}
    return target in full_cache


def recent_query_covers_target(execution_history: dict, target: str) -> bool:
    target = target.strip()
    for entry in execution_history.get("recent", [])[-8:]:
        if entry.get("kind") != "query" and not is_query_tool(entry.get("tool", "")):
            continue
        query_target = entry.get("query_target")
        if query_target == target:
            return True
        query_targets = entry.get("query_targets") or []
        if target in query_targets:
            return True
        query_result = entry.get("query_result") or {}
        if query_result.get("name") == target:
            return True
        objects = query_result.get("objects") or []
        if any(obj.get("name") == target for obj in objects if isinstance(obj, dict)):
            return True
    return False


def _is_risky_call(call: dict) -> bool:
    tool = call.get("tool")
    if tool in RISKY_TOOLS:
        return True
    args = call.get("args") or {}
    return bool(args.get("face") or args.get("face_selector") or args.get("edge_selector"))


def _query_tool_for_error(error: dict) -> str:
    tool = error.get("tool")
    return QUERY_BY_TOOL.get(tool, "get_object_detail")
