"""提示词集中目录加载与关键片段冒烟（仅 live chat 路径）。"""

from pathlib import Path

from app.design import format_design_brief
from app.prompts import clear_cache, load_template, render
from app.workflow import chat as chat_mod

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_all_named_templates_load():
    clear_cache()
    names = [
        "chat_core",
        "chat_plan_on",
        "chat_plan_off",
        "chat_vision_on",
        "chat_vision_off",
        "compress",
        "vision",
        "design_brief",
        "packs/general_part",
        "packs/gear",
        "packs/humanoid",
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


def test_chat_core_code_mode():
    prompt = chat_mod.build_chat_system_prompt(
        message="建一辆车",
        user_goal="建一辆车",
        plan_mode=True,
        vision_on=False,
    )
    assert "Code Mode" in prompt or "参数化建模" in prompt
    assert "execute_cad_program" in prompt
    assert "cad.delete" in prompt
    assert "Plan 模式（已开启）" in prompt
    assert "当前未启用视觉辅助" in prompt
    assert "右" in prompt and "+X" in prompt
    assert "前" in prompt and "-Y" in prompt
    assert "闭合截面" in prompt or "拉伸" in prompt
    assert "cad.extrude" in prompt
    assert "rot_y=90" in prompt
    assert "默认轴" in prompt or "轴沿" in prompt
    assert "cad.hole" in prompt and "axis" in prompt
    assert "cad.extrude" in prompt and "direction" in prompt
    assert "polar_pattern" in prompt or "pivot" in prompt or "世界原点" in prompt
    # 不再注入旧工作集 / 规则包
    assert "### create_box" not in prompt
    assert "当前工具工作集" not in prompt


def test_vision_on_mentions_capture_views():
    prompt = chat_mod.build_chat_system_prompt(
        message="建箱子",
        user_goal="建箱子",
        plan_mode=False,
        vision_on=True,
    )
    assert "capture_views" in prompt
    assert "cad.delete" in prompt
    assert "warn" in prompt.lower() or "细节" in prompt
    assert "询问" in prompt or "question" in prompt


def test_chat_core_requires_contact_overlap_for_booleans():
    """D6：相切 fuse 会静默裂成多实体，规则必须进主提示词而不是只写在 recipes。"""
    text = load_template("chat_core")
    assert "轻嵌" in text
    assert "1mm" in text
    assert "相切" in text


def test_chat_core_pattern_rule_is_conditional_not_absolute():
    """D5：主提示词不再绝对化，否则与 recipes 的直算写法互相打架。"""
    text = load_template("chat_core")
    assert "polar_pattern" in text
    assert "未 move/rotate" in text
    assert "循环内新建" in text
    assert "一律走 pattern" not in text


def test_chat_core_example_acceptance_includes_geometric_check():
    """示例里的 acceptance 会被模型照抄，必须满足 F2 的几何检查硬约束。"""
    text = load_template("chat_core")
    assert '"bbox_size"' in text or '"solid_count"' in text


def test_plan_rules_require_geometric_acceptance():
    text = load_template("chat_plan_on")
    assert "硬约束" in text
    assert "几何检查" in text
    assert "冻结" in text


def test_recipes_and_writer_defer_to_canonical_pattern_rule():
    """配方文档不得再写与主提示词相反的绝对规则。"""
    recipes = (REPO_ROOT / "docs" / "cad_modeling_recipes.md").read_text(encoding="utf-8")
    writer = (REPO_ROOT / "docs" / "cad_script_writer_prompt.md").read_text(encoding="utf-8")
    assert "chat_core.md" in recipes
    assert "chat_core.md" in writer
    for text in (recipes, writer):
        assert "不用 pattern" not in text
        assert "必须用阵列" not in text
        assert "禁止 `for`" not in text


def test_brief_still_injects_user_input():
    brief = "总长 4500mm，左右对称"
    text = format_design_brief(brief, goal="车")
    assert brief in text
    prompt = chat_mod.build_chat_system_prompt(
        message=brief,
        user_goal=brief,
        plan_mode=False,
        vision_on=True,
    )
    assert brief in prompt
