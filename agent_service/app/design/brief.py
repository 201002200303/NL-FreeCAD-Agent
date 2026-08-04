"""设计需求原文（design brief）——跨步骤保持不变的那份约束。

高层计划刻意剥掉尺寸、坐标与工艺细节：阶段只描述角色顺序，这对阶段规划是对的。
但单步工具调用需要的恰好是被剥掉的那部分，而记忆包只留一句 `goal`，
于是每一步都在重新猜尺寸和坐标系。

本模块是需求原文唯一的保管处：原样保留，渲染进 chat system / design brief。
"""

from __future__ import annotations

from app.prompts import render

MAX_BRIEF_CHARS = 4000


def resolve_brief_text(user_input: str = "", high_level_plan: dict | None = None) -> str:
    """取需求原文。next_step 直接有 user_input；evaluate 只能从高层计划里回取。"""
    text = (user_input or "").strip()
    if text:
        return text
    return ((high_level_plan or {}).get("user_input") or "").strip()


def format_design_brief(
    user_input: str = "",
    *,
    high_level_plan: dict | None = None,
    goal: str = "",
    max_chars: int = MAX_BRIEF_CHARS,
) -> str:
    """渲染成提示词片段；无需求原文时返回空串，调用方直接拼接即可。

    措辞模板见 app/prompts/design_brief.md。
    """
    text = resolve_brief_text(user_input, high_level_plan)
    if not text:
        return ""

    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…（原文过长已截断，未列出的约束依然有效）"

    goal = (goal or "").strip()
    goal_line = ""
    if goal and goal not in text:
        goal_line = f"\n（阶段计划目标摘要：{goal}）"

    return render("design_brief", BRIEF_TEXT=text, GOAL_LINE=goal_line).rstrip()
