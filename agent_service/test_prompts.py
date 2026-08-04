"""提示词集中目录加载与关键片段冒烟（仅 live chat 路径）。"""

from app.design import format_design_brief
from app.prompts import clear_cache, load_template, render
from app.workflow import chat as chat_mod


def test_all_named_templates_load():
    clear_cache()
    names = [
        "chat_system",
        "chat_plan_on",
        "chat_plan_off",
        "chat_vision_on",
        "chat_vision_off",
        "compress",
        "vision",
        "design_brief",
    ]
    for name in names:
        text = load_template(name)
        assert text
        assert "<!--" not in text


def test_render_replaces_placeholders():
    out = render("design_brief", BRIEF_TEXT="总长4500", GOAL_LINE="")
    assert "总长4500" in out
    assert "[[BRIEF_TEXT]]" not in out
    assert "原始需求" in out


def test_chat_system_uses_md():
    prompt = chat_mod._build_chat_system_prompt(
        plan_mode=True, vision_on=False, user_goal="建一辆车"
    )
    assert "CAD 建模工程师" in prompt or "coding agent" in prompt
    assert "Plan 模式（已开启）" in prompt
    assert "当前未启用视觉辅助" in prompt
    assert "建模原则" in prompt
    assert "place_relative" in prompt
    assert "right=+X" in prompt or "right` / `left`" in prompt or "右=+X" in prompt
    assert "阶段完成门闩" in prompt
    assert 'forward": "-Y"' in prompt or "forward=-Y" in prompt or "前=-Y" in prompt
    assert "没有 `mirror`" in prompt or "不用 mirror" in prompt
    assert "linear_pattern" in prompt or "polar_pattern" in prompt


def test_brief_still_injects_user_input():
    brief = "总长 4500mm，左右对称"
    text = format_design_brief(brief, goal="车")
    assert brief in text
    prompt = chat_mod._build_chat_system_prompt(
        plan_mode=False, vision_on=True, user_goal=brief
    )
    assert brief in prompt
    assert "对称" in prompt or "linear_pattern" in prompt
