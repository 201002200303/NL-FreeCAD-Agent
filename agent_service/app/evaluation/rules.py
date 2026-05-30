"""Deterministic validation rules for step evaluation."""

from typing import Any, Optional


def _object_names(document_state) -> set[str]:
    if not document_state:
        return set()
    objects = document_state.objects if hasattr(document_state, "objects") else document_state.get("objects", [])
    return {obj.name if hasattr(obj, "name") else obj.get("name", "") for obj in objects}


def _get_object(document_state, name: str) -> Optional[Any]:
    if not document_state or not name:
        return None
    objects = document_state.objects if hasattr(document_state, "objects") else document_state.get("objects", [])
    for obj in objects:
        obj_name = obj.name if hasattr(obj, "name") else obj.get("name", "")
        if obj_name == name:
            return obj
    return None


def run_deterministic_checks(
    last_tool_call: dict,
    execution_result: dict,
    document_state,
) -> dict:
    """Run deterministic checks on execution result.

    Returns:
        {
            "passed": bool,
            "issues": list[str],
            "suggested_decision": "continue" | "repair" | "skip_and_continue" | None,
        }
    """
    issues: list[str] = []
    status = execution_result.get("status", "")

    if status == "error":
        msg = execution_result.get("message", "未知错误")
        return {
            "passed": False,
            "issues": [f"工具执行失败: {msg}"],
            "suggested_decision": "repair",
        }

    if status != "success":
        return {
            "passed": False,
            "issues": [f"未知执行状态: {status}"],
            "suggested_decision": "skip_and_continue",
        }

    # Check produced objects exist in document
    produced = execution_result.get("produced_objects", [])
    names = _object_names(document_state)
    for obj_name in produced:
        if obj_name and obj_name not in names:
            issues.append(f"预期对象 '{obj_name}' 未出现在文档中")

    # Check expected_effect from tool call
    expected = last_tool_call.get("expected_effect") or {}
    expected_obj = expected.get("new_object")
    if expected_obj and expected_obj not in names:
        issues.append(f"预期新对象 '{expected_obj}' 未创建")

    expected_type = expected.get("type")
    if expected_obj and expected_type:
        obj = _get_object(document_state, expected_obj)
        if obj:
            obj_type = obj.type if hasattr(obj, "type") else obj.get("type", "")
            if obj_type != expected_type:
                issues.append(f"对象 '{expected_obj}' 类型为 {obj_type}，预期 {expected_type}")

    # Check topology validity for produced objects
    for obj_name in produced:
        obj = _get_object(document_state, obj_name)
        if not obj:
            continue
        topology = obj.topology if hasattr(obj, "topology") else obj.get("topology")
        if topology:
            is_valid = topology.is_valid if hasattr(topology, "is_valid") else topology.get("is_valid", True)
            if is_valid is False:
                issues.append(f"对象 '{obj_name}' 的 Shape 无效")

    # Check visibility: if source should be hidden
    if expected.get("source_should_be_hidden"):
        source = expected.get("source") or execution_result.get("source_objects", [None])[0] if execution_result.get("source_objects") else None
        if source:
            src_obj = _get_object(document_state, source)
            if src_obj:
                visible = src_obj.visible if hasattr(src_obj, "visible") else src_obj.get("visible", True)
                if visible:
                    issues.append(f"源对象 '{source}' 应该被隐藏但仍可见")

    if issues:
        return {
            "passed": False,
            "issues": issues,
            "suggested_decision": "repair",
        }

    return {
        "passed": True,
        "issues": [],
        "suggested_decision": "continue",
    }
