"""Modeling knowledge retrieval tests."""

from app.modeling_knowledge import match_knowledge, format_knowledge_for_prompt
from app.llm.llm_provider import _build_high_level_plan_prompt


def test_match_vehicle():
    hits = match_knowledge("做一个小车", limit=2)
    ids = [h["pattern_id"] for h in hits]
    assert "vehicle" in ids


def test_match_enclosure():
    hits = match_knowledge("做个盒子外壳", limit=2)
    ids = [h["pattern_id"] for h in hits]
    assert "enclosure" in ids


def test_match_gear():
    hits = match_knowledge("画一个标准的齿轮", limit=2)
    ids = [h["pattern_id"] for h in hits]
    assert "gear" in ids


def test_match_mouse():
    hits = match_knowledge("做一个电脑鼠标外壳", limit=2)
    ids = [h["pattern_id"] for h in hits]
    assert "mouse" in ids


def test_match_stepped_shaft():
    hits = match_knowledge("建模一根阶梯轴", limit=2)
    ids = [h["pattern_id"] for h in hits]
    assert "stepped_shaft" in ids


def test_no_match_for_generic_circle():
    hits = match_knowledge("画个圆", limit=2)
    # may still hit coordinate_conventions if "坐标" not present — "圆" alone should not hit vehicle/enclosure
    ids = {h["pattern_id"] for h in hits}
    assert "vehicle" not in ids
    assert "enclosure" not in ids
    assert "gear" not in ids



def test_start_plan_prompt_includes_knowledge():
    prompt = _build_high_level_plan_prompt(None, user_input="创建一个带轮子的小车模型")
    assert "建模参考" in prompt
    assert "vehicle" in prompt or "车辆" in prompt


def test_format_knowledge():
    text = format_knowledge_for_prompt(match_knowledge("支架底座", limit=1))
    assert "建模参考" in text
    assert "bracket" in text
