"""vision_memory 门控与空文档跳过。"""

from app.vision.memory import (
    count_visible_objects,
    empty_vision_memory,
    note_vision_revise_attempt,
    should_allow_vision_revise,
    update_vision_memory,
)
from app.vision.service import format_vision_for_prompt, needs_code_revision


def test_count_visible_objects():
    assert count_visible_objects(None) == 0
    assert count_visible_objects({"objects": []}) == 0
    assert (
        count_visible_objects(
            {
                "objects": [
                    {"name": "A", "visible": True},
                    {"name": "B", "visible": False},
                ]
            }
        )
        == 1
    )


def test_warn_does_not_allow_auto_revise():
    mem = empty_vision_memory()
    vision = {"verdict": "warn", "skipped": False, "issues": ["略方块"]}
    mem = update_vision_memory(mem, soft_plan=None, vision_result=vision)
    assert should_allow_vision_revise(mem, vision) is False
    assert any(i.get("status") == "ask_user" for i in mem["open_issues"])


def test_bad_allows_until_budget():
    plan = {
        "items": [
            {"id": "1", "title": "骨架", "status": "in_progress", "acceptance": "四肢齐全"}
        ]
    }
    mem = empty_vision_memory(max_revises=2)
    bad = {"verdict": "bad", "skipped": False, "issues": ["右臂悬空"]}
    mem = update_vision_memory(mem, soft_plan=plan, vision_result=bad)
    assert should_allow_vision_revise(mem, bad) is True
    mem = note_vision_revise_attempt(mem)
    assert mem["revise_count_in_phase"] == 1
    assert should_allow_vision_revise(mem, bad) is True
    mem = note_vision_revise_attempt(mem)
    assert mem["stop_reason"] == "budget"
    assert should_allow_vision_revise(mem, bad) is False


def test_phase_change_resets_budget():
    plan1 = {"items": [{"id": "1", "title": "骨架", "status": "in_progress"}]}
    plan2 = {"items": [{"id": "2", "title": "装甲", "status": "in_progress"}]}
    mem = empty_vision_memory()
    mem = update_vision_memory(mem, soft_plan=plan1, vision_result=None)
    mem = note_vision_revise_attempt(mem)
    mem = note_vision_revise_attempt(mem)
    assert mem["stop_reason"] == "budget"
    mem = update_vision_memory(mem, soft_plan=plan2, vision_result=None)
    assert mem["phase_id"] == "2"
    assert mem["revise_count_in_phase"] == 0
    assert mem["stop_reason"] is None


def test_format_warn_asks_user():
    text = format_vision_for_prompt(
        {"ok": True, "verdict": "warn", "summary": "略方", "issues": ["倒角少"]},
        allow_revise=False,
    )
    assert "不要自动改码" in text or "询问" in text
    assert needs_code_revision({"verdict": "warn"}) is False
