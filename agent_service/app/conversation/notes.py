"""把系统侧发生的事翻译成模型读得懂的旁白。

这些事件不是模型说的、也不是模型被问的，但它必须知道，否则会带着过时的
记忆继续推进——最典型的就是暂停期间用户手工改了文档。
"""

from __future__ import annotations

_MAX_NAMES = 12


def _names(items: list | None) -> str:
    names = []
    for item in items or []:
        if isinstance(item, dict):
            names.append(str(item.get("name") or item.get("label") or item))
        else:
            names.append(str(item))
    if not names:
        return ""
    head = names[:_MAX_NAMES]
    suffix = f" 等 {len(names)} 个" if len(names) > _MAX_NAMES else ""
    return "、".join(head) + suffix


def format_resume_note(document_changes: dict | None) -> str:
    """会话恢复时的状态断层说明。无手工改动则返回空串。"""
    if not document_changes or not document_changes.get("changed", True):
        return ""

    lines = [
        "【会话中断恢复】上面这些回合发生在本次中断之前。"
        "期间用户在 FreeCAD 里手工改过文档，你的记忆已经和实际状态不一致：",
    ]
    if added := _names(document_changes.get("added")):
        lines.append(f"- 新增对象：{added}")
    if removed := _names(document_changes.get("removed")):
        lines.append(f"- 已被删除：{removed}（不要再引用这些名字）")
    if modified := _names(document_changes.get("modified")):
        lines.append(f"- 被修改：{modified}")
    if not any(
        document_changes.get(k) for k in ("added", "removed", "modified")
    ) and (summary := document_changes.get("summary")):
        lines.append(f"- {summary}")

    lines.append(
        "请以下面这轮给出的文档状态为准，必要时先 query 确认，不要沿用中断前的假设。"
    )
    return "\n".join(lines)
