"""闭环修复回归测试：需求原文注入、自声明验证器、LLM 重试。"""

import pytest

from app.design import format_design_brief, resolve_brief_text
from app.evaluation.harness import should_advance_abstract_step
from app.evaluation.validators import blocking_failures, is_blocking_validator
from app.llm import llm_provider
from app.schemas.cad_state import CADObject, DocumentState
from app.workflow.service import evaluate_step_node


# ── 设计需求原文 ────────────────────────────────────────────────────

BRIEF = "建一辆车：总长 4500mm，轴距 2450mm，轮距 1600mm，车头朝 +X，左右关于 XZ 平面对称。"


def test_brief_falls_back_to_high_level_plan():
    """evaluate 没有 user_input 参数，只能从 high_level_plan 回取原文。"""
    assert resolve_brief_text("", {"user_input": BRIEF}) == BRIEF
    assert resolve_brief_text(BRIEF, {"user_input": "别的"}) == BRIEF
    assert resolve_brief_text("", {}) == ""


def test_start_plan_persists_user_input_on_high_level_plan(monkeypatch):
    """上一轮 brief 回取依赖此字段；start_plan 必须写入。"""
    from app.workflow import service as wf

    monkeypatch.setattr(
        wf,
        "generate_high_level_plan",
        lambda *a, **k: {
            "status": "ok",
            "goal": "建车",
            "phases": [{"phase_id": "P1", "intent": "车身", "title": "车身"}],
        },
    )
    monkeypatch.setattr(
        wf,
        "build_queue_from_high_level_plan",
        lambda plan: type(
            "Q",
            (),
            {
                "model_dump": lambda self, mode="json": {
                    "recipe_id": "llm_session",
                    "current_step_id": "P1",
                    "steps": [{"step_id": "P1", "title": "车身"}],
                }
            },
        )(),
    )
    monkeypatch.setattr(
        wf,
        "resolve_current_abstract_step",
        lambda q: {"step_id": "P1", "title": "车身"},
    )
    result = wf.start_plan(user_input=BRIEF)
    assert result["status"] == "ok"
    assert result["high_level_plan"]["user_input"] == BRIEF


def test_brief_is_empty_when_no_input():
    assert format_design_brief("", high_level_plan={}) == ""


def test_brief_keeps_dimensions_verbatim():
    text = format_design_brief(BRIEF, goal="建一辆车")
    assert "4500mm" in text and "2450mm" in text and "1600mm" in text
    assert "最高优先级" in text


def test_brief_truncates_but_flags_it():
    text = format_design_brief("x" * 9000, max_chars=100)
    assert "已截断" in text
    assert len(text) < 600


def test_next_step_prompt_contains_original_brief():
    """回归：修复前 user_input 是形参却从未进入提示词正文。"""
    prompt = llm_provider._build_next_step_prompt(
        high_level_plan={"goal": "建一辆车", "phases": [{"phase_id": "P1", "intent": "车身"}]},
        current_phase_id="P1",
        execution_history={},
        name_map={},
        user_input=BRIEF,
    )
    assert "4500mm" in prompt
    assert "2450mm" in prompt


def test_evaluate_prompt_contains_original_brief():
    prompt = llm_provider._build_evaluate_prompt(
        high_level_plan={"user_input": BRIEF, "goal": "建一辆车", "phases": []},
        current_phase_id="P1",
    )
    assert "4500mm" in prompt


def test_next_step_prompt_states_mirror_and_fillet_rules():
    prompt = llm_provider._build_next_step_prompt(
        high_level_plan={"goal": "g", "phases": [{"phase_id": "P1", "intent": "i"}]},
        current_phase_id="P1",
        execution_history={},
        name_map={},
        user_input="建一辆车",
    )
    assert "mirror" in prompt
    assert "add_chamfer" in prompt


# ── 验证器闭环 ──────────────────────────────────────────────────────

def _state_with_validators(validators):
    return {
        "session_id": "s1",
        "user_input": "test",
        "high_level_plan": {"phases": [{"phase_id": "P1", "intent": "x"}]},
        "current_phase_id": "P1",
        "last_tool_call": {
            "call_id": "P1_S1",
            "tool": "create_box",
            "args": {"name": "Missing"},
            "expected_effect": {"new_object": "Missing", "validators": validators},
        },
        "execution_result": {"status": "success", "produced_objects": ["Missing"]},
        "document_state": DocumentState(document_name="doc", objects=[]),
        "before_state": DocumentState(document_name="doc", objects=[]),
        "execution_history": {"recent": []},
    }


def test_self_declared_validators_run_without_strict_mode(monkeypatch):
    """修复前 expected_effect.validators 被恒 False 的 strict_validation 一起吞掉。"""
    monkeypatch.setattr(
        "app.workflow.service.evaluate_step_result",
        lambda **kw: {"decision": "continue", "phase_status": "completed",
                      "message": "ok", "repair_tool_calls": []},
    )
    result = evaluate_step_node(_state_with_validators(["verify_object_exists"]))["evaluate_result"]
    names = [r["validator"] for r in result["validator_results"]]
    assert "verify_object_exists" in names


def test_blocking_validator_failure_downgrades_decision(monkeypatch):
    """对象没建出来时不能被 LLM 的 continue/completed 蒙混过关。"""
    monkeypatch.setattr(
        "app.workflow.service.evaluate_step_result",
        lambda **kw: {"decision": "continue", "phase_status": "completed",
                      "message": "ok", "repair_tool_calls": []},
    )
    result = evaluate_step_node(_state_with_validators(["verify_object_exists"]))["evaluate_result"]
    assert result["phase_status"] == "in_progress"
    assert any("verify_object_exists" in i for i in result["deterministic_issues"])


def test_non_blocking_validator_only_warns(monkeypatch):
    monkeypatch.setattr(
        "app.workflow.service.evaluate_step_result",
        lambda **kw: {"decision": "continue", "phase_status": "completed",
                      "message": "ok", "repair_tool_calls": []},
    )
    state = _state_with_validators(["verify_grounded"])
    state["document_state"] = DocumentState(
        document_name="doc",
        objects=[CADObject(name="Missing", label="Missing", type="Part::Box")],
    )
    result = evaluate_step_node(state)["evaluate_result"]
    assert result["phase_status"] != "in_progress"


def test_should_advance_uses_validator_results():
    blocking = [{"validator": "verify_object_exists", "passed": False, "error_code": "OBJECT_NOT_FOUND"}]
    warning = [{"validator": "verify_grounded", "passed": False, "error_code": "NOT_GROUNDED"}]

    assert should_advance_abstract_step(execution_passed=True, validator_results=[]) is True
    assert should_advance_abstract_step(execution_passed=True, validator_results=warning) is True
    assert should_advance_abstract_step(execution_passed=True, validator_results=blocking) is False
    assert should_advance_abstract_step(execution_passed=False, validator_results=[]) is False


def test_blocking_policy_has_single_source():
    assert is_blocking_validator({"validator": "verify_shape_valid"}) is True
    assert is_blocking_validator({"validator": "verify_grounded"}) is False
    assert blocking_failures(None) == []


# ── LLM 重试 ───────────────────────────────────────────────────────

def test_call_llm_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(llm_provider, "_get_llm_config", lambda: ("k", "u", "m"))
    monkeypatch.setattr(llm_provider.time, "sleep", lambda _: None)
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("connection reset")
        return {"decision": "execute"}, None, None, '{"decision":"execute"}'

    monkeypatch.setattr(llm_provider, "_attempt_llm_call", flaky)
    assert llm_provider.call_llm("u", "s") == {"decision": "execute"}
    assert len(calls) == 3


def test_call_llm_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(llm_provider, "_get_llm_config", lambda: ("k", "u", "m"))
    monkeypatch.setattr(llm_provider.time, "sleep", lambda _: None)
    calls = []

    def always_fail(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("boom")

    monkeypatch.setattr(llm_provider, "_attempt_llm_call", always_fail)
    assert llm_provider.call_llm("u", "s") is None
    assert len(calls) == llm_provider.LLM_MAX_ATTEMPTS


def test_call_llm_retries_on_unparseable_json(monkeypatch):
    """P4 abort 的另一半成因：返回了但 JSON 截断。"""
    monkeypatch.setattr(llm_provider, "_get_llm_config", lambda: ("k", "u", "m"))
    monkeypatch.setattr(llm_provider.time, "sleep", lambda _: None)
    calls = []

    def bad_json(*args, **kwargs):
        calls.append(1)
        if len(calls) < 2:
            return None, object(), "JSONDecodeError: truncated", "{trunc"
        return {"ok": True}, None, None, '{"ok":true}'

    monkeypatch.setattr(llm_provider, "_attempt_llm_call", bad_json)
    assert llm_provider.call_llm("u", "s") == {"ok": True}
    assert len(calls) == 2


def test_call_llm_without_api_key_does_not_retry(monkeypatch):
    monkeypatch.setattr(llm_provider, "_get_llm_config", lambda: ("", "u", "m"))

    def boom(*args, **kwargs):
        raise AssertionError("should not be called without api key")

    monkeypatch.setattr(llm_provider, "_attempt_llm_call", boom)
    assert llm_provider.call_llm("u", "s") is None


def test_graph_package_is_gone():
    with pytest.raises(ImportError):
        __import__("app.graph.nodes")
