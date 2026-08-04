"""Query-before-act policy for spatially risky CAD tool calls.

V0.7: batch-aware. A target that is produced by an *earlier* tool call in the
same LLM batch is treated as "will exist when this call runs" and does NOT
trigger a QUERY_REQUIRED. This prevents the agent from throwing away a
perfectly valid `create → boolean` batch and then looping on
"Object not found" queries for objects that were supposed to be created
in that same batch.
"""

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
    "align_objects",
    "place_relative",
    "distribute_along",
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
    "align_objects": "get_object_detail",
    "place_relative": "get_object_detail",
    "distribute_along": "get_object_detail",
    "cut_hole": "get_object_detail",
    "boolean_cut": "get_object_detail",
    "boolean_fuse": "get_object_detail",
    "boolean_common": "get_object_detail",
}

# Boolean ops only need the object to exist; spatial cache is optional.
EXISTENCE_SUFFICIENT_TOOLS = {
    "boolean_cut",
    "boolean_fuse",
    "boolean_common",
}

# Fields that reference *existing* objects (the inputs to a risky call).
TARGET_FIELDS = (
    "target",
    "reference",
    "base",
    "tool",
    "obj_a",
    "obj_b",
    "part1",
    "part2",
)

# Fields that declare the *new* object produced by a creative call.
PRODUCED_NAME_FIELDS = ("name", "result_name", "fuse_name")


def is_query_tool(tool_name: str) -> bool:
    return tool_name in QUERY_TOOLS


def extract_target_from_call(call: dict) -> str | None:
    """First referenced existing-object name (kept for backward compat)."""
    args = call.get("args") or {}
    for field in TARGET_FIELDS:
        value = args.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_targets_from_call(call: dict) -> list[str]:
    """All referenced existing-object names in this call (dedup, order-kept)."""
    args = call.get("args") or {}
    targets: list[str] = []
    seen: set[str] = set()
    for field in TARGET_FIELDS:
        value = args.get(field)
        if isinstance(value, str) and value.strip():
            t = value.strip()
            if t not in seen:
                seen.add(t)
                targets.append(t)
    # distribute_along: "A,B,C" or list
    raw_targets = args.get("targets")
    names: list[str] = []
    if isinstance(raw_targets, str):
        names = [n.strip() for n in raw_targets.split(",") if n.strip()]
    elif isinstance(raw_targets, list):
        names = [str(n).strip() for n in raw_targets if str(n).strip()]
    for t in names:
        if t not in seen:
            seen.add(t)
            targets.append(t)
    return targets


def _produced_names(call: dict) -> list[str]:
    """Names this single call will create, from expected_effect or args."""
    names: list[str] = []

    effect = call.get("expected_effect") or {}
    if isinstance(effect, dict):
        new_obj = effect.get("new_object")
        if isinstance(new_obj, str) and new_obj.strip():
            names.append(new_obj.strip())
        new_objs = effect.get("new_objects")
        if isinstance(new_objs, list):
            for n in new_objs:
                if isinstance(n, str) and n.strip():
                    names.append(n.strip())

    # Fallback: infer from args. Creative tools declare the new name via
    # `name` (create_*, boolean_*, mirror, copy_object, sketch, pad, ...)
    # or `result_name` (scale, add_fillet, add_chamfer, cut_hole).
    tool = call.get("tool") or ""
    if tool and not is_query_tool(tool):
        args = call.get("args") or {}
        for field in PRODUCED_NAME_FIELDS:
            value = args.get(field)
            if isinstance(value, str) and value.strip():
                t = value.strip()
                if t not in names:
                    names.append(t)
        # polar/linear_pattern create target_2.. or {prefix}2.. plus optional fuse
        if tool in {"polar_pattern", "linear_pattern"}:
            try:
                count = int(args.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            target = str(args.get("target") or "").strip()
            prefix = str(args.get("name_prefix") or "").strip()
            for i in range(2, count + 1):
                n = f"{prefix}{i}" if prefix else (f"{target}_{i}" if target else "")
                if n and n not in names:
                    names.append(n)

    return names


def _batch_producer_index(tool_calls: list[dict]) -> list[set[str]]:
    """For each index i, the set of object names produced by calls [0, i)."""
    produced_so_far: set[str] = set()
    index: list[set[str]] = []
    for call in tool_calls or []:
        index.append(set(produced_so_far))
        for name in _produced_names(call):
            produced_so_far.add(name)
    return index


def _names_from_document_state(document_state) -> set[str]:
    names: set[str] = set()
    if document_state is None:
        return names
    if isinstance(document_state, dict):
        objects = document_state.get("objects") or []
    else:
        objects = getattr(document_state, "objects", None) or []
    for obj in objects:
        if isinstance(obj, dict):
            name = obj.get("name")
        else:
            name = getattr(obj, "name", None)
        if isinstance(name, str) and name.strip():
            names.add(name.strip())
    return names


def _names_from_object_memory(session_memory: dict | None) -> set[str]:
    if not session_memory:
        return set()
    memory = session_memory.get("object_memory") or {}
    return {str(k).strip() for k in memory.keys() if str(k).strip()}


def target_is_known(
    target: str,
    *,
    produced_before: set[str] | None = None,
    document_state=None,
    session_memory: dict | None = None,
) -> bool:
    """True when target already exists or will exist before this call runs."""
    t = (target or "").strip()
    if not t:
        return False
    if produced_before and t in produced_before:
        return True
    if t in _names_from_document_state(document_state):
        return True
    if t in _names_from_object_memory(session_memory):
        return True
    return False


def validate_query_before_act(
    tool_calls: list[dict],
    execution_history: dict | None,
    session_memory: dict | None = None,
    document_state=None,
) -> list[dict]:
    errors: list[dict] = []
    batch_produced = _batch_producer_index(tool_calls or [])
    for i, call in enumerate(tool_calls or []):
        tool = call.get("tool")
        if not tool or is_query_tool(tool):
            continue
        if not _is_risky_call(call):
            continue
        produced_before = batch_produced[i] if i < len(batch_produced) else set()
        targets = extract_targets_from_call(call)
        if not targets:
            single = extract_target_from_call(call)
            targets = [single] if single else []
        for target in targets:
            known = target_is_known(
                target,
                produced_before=produced_before,
                document_state=document_state,
                session_memory=session_memory,
            )
            # Boolean: existence (doc / memory / earlier in batch) is enough.
            if known and tool in EXISTENCE_SUFFICIENT_TOOLS:
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
    """Only treat a cache hit as coverage when it carries usable spatial facts."""
    from app.memory.geometry_facts import has_spatial_facts

    target = target.strip()
    if not target or not session_memory:
        return False
    query_cache = session_memory.get("query_cache") or {}
    entry = query_cache.get(target)
    if entry and has_spatial_facts(cache_entry=entry):
        return True
    full_cache = session_memory.get("_query_cache_full") or {}
    entry = full_cache.get(target)
    return bool(entry and has_spatial_facts(cache_entry=entry))


def recent_query_covers_target(execution_history: dict, target: str) -> bool:
    from app.memory.geometry_facts import has_spatial_facts

    target = target.strip()
    for entry in execution_history.get("recent", [])[-8:]:
        if entry.get("kind") != "query" and not is_query_tool(entry.get("tool", "")):
            continue
        query_result = entry.get("query_result") or {}
        matched = False
        query_target = entry.get("query_target")
        if query_target == target:
            matched = True
        query_targets = entry.get("query_targets") or []
        if target in query_targets:
            matched = True
        if query_result.get("name") == target:
            matched = True
        objects = query_result.get("objects") or []
        if any(obj.get("name") == target for obj in objects if isinstance(obj, dict)):
            matched = True
        if matched and has_spatial_facts(query_result=query_result):
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
