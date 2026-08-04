"""提示词集中目录加载与关键片段冒烟。"""

from app.design import format_design_brief
from app.llm import llm_provider
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
        "high_level_plan",
        "next_step",
        "evaluate",
        "legacy_plan",
        "cad_spec",
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
    assert "CAD coding agent" in prompt
    assert "Plan 模式（已开启）" in prompt
    assert "当前未启用视觉辅助" in prompt


def test_brief_and_next_step_still_inject_user_input():
    brief = "总长 4500mm，左右对称"
    text = format_design_brief(brief, goal="车")
    assert brief in text
    prompt = llm_provider._build_next_step_prompt(
        high_level_plan={
            "goal": "车",
            "user_input": brief,
            "phases": [
                {
                    "phase_id": "P1",
                    "title": "车身",
                    "intent": "主体",
                    "success_criteria": ["存在车身"],
                }
            ],
        },
        current_phase_id="P1",
        execution_history={},
        name_map={},
        user_input=brief,
    )
    assert brief in prompt
    assert "对称件必须用" in prompt
