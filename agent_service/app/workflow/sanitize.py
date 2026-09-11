"""客户端回传数据的清洗：畸形结构降级为「忽略」，而不是把整轮打成 500。

``ChatRequest`` 只把 ``tool_results`` 约束到 ``list[dict]``、``session_memory``
约束到 ``dict``，内部值不校验；下游宿主逻辑却直接 ``.get()`` / ``.items()``。
一旦某轮状态变脏，客户端每轮原样重发 → 会话永久 500，用户无法自救。
这里在入口把结构补齐，保证下游拿到的一定是预期形状。
"""


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


def sanitize_tool_results(results: list | None) -> list[dict] | None:
    """把执行回执规范成 ``[{tool_call: dict, execution_result: dict}]``。

    非 dict 的条目直接丢弃；``tool_call`` / ``execution_result`` 不是 dict 时
    置空，让下游按「无信息」处理而不是崩。
    """
    if not results:
        return None
    cleaned = []
    for item in results:
        if not isinstance(item, dict):
            continue
        call = item.get("tool_call")
        result = item.get("execution_result")
        cleaned.append({
            "tool_call": call if isinstance(call, dict) else {},
            "execution_result": result if isinstance(result, dict) else {},
        })
    return cleaned or None


def sanitize_memory_pack(pack: dict | None) -> dict | None:
    """规范客户端 session_memory，只保证宿主消费的索引字段形状正确。

    ``object_memory`` / ``query_cache`` 必须是「dict of dict」，
    ``current_target`` 必须是 str（否则拿它做 dict 成员判断会 TypeError）。
    形状不对就整段丢弃，让提示词退回按 document_state 渲染。
    """
    if not isinstance(pack, dict):
        return None
    pack = dict(pack)
    for field in ("object_memory", "query_cache"):
        value = pack.get(field)
        if isinstance(value, dict):
            pack[field] = {k: v for k, v in value.items() if isinstance(v, dict)}
        else:
            pack.pop(field, None)
    target = pack.get("current_target")
    if target is not None and not isinstance(target, str):
        pack.pop("current_target", None)
    return pack
