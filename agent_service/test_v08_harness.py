"""V0.8 CAD Harness core tests."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.abstract_steps.planner import (
    advance_step_queue,
    build_step_queue,
    build_queue_from_phases,
    tool_calls_for_abstract_step,
    is_harness_session,
)
from app.abstract_steps.schemas import AbstractStepQueue
from app.cad_spec.generator import generate_cad_spec
from app.evaluation.harness import (
    apply_abstract_step_advancement,
    should_advance_abstract_step,
    resolve_validator_names,
)
from app.evaluation.validators import run_geometry_validators
from app.graph.nodes import plan_next_step_node, evaluate_step_node
from app.inspection.impact_map import build_impact_map
from app.main import app
from app.recipes.registry import select_recipe
from app.schemas.cad_state import CADObject, DocumentState, TopologySummary
from app.debug.replay_trace import replay_trace


client = TestClient(app)


@pytest.fixture(autouse=True)
def _disable_llm_spec_by_default(monkeypatch):
    """Keep tests fast/deterministic; individual tests can override."""
    monkeypatch.setattr("app.llm.llm_provider.generate_cad_spec_with_llm", lambda user_input: None)


def test_cad_spec_has_no_tool_calls():
    result = generate_cad_spec("create a 100x60x20 box with fillet radius 3")
    assert result.status == "ok"
    data = result.cad_spec.model_dump(mode="json")
    assert "tool_calls" not in data
    assert "plan" not in data
    assert [feature["type"] for feature in data["features"]] == ["box", "fillet"]


def test_impact_map_blocks_high_risk_without_target():
    spec = generate_cad_spec("add a hole radius 5").cad_spec
    impact = build_impact_map(spec, DocumentState(document_name="empty"))
    assert impact.blocked is True
    assert impact.requires_confirmation is True


def test_recipe_skips_complex_model_types():
    from app.cad_spec.schemas import CADFeature, CADSpec

    spec = CADSpec(
        model_type="robot",
        features=[
            CADFeature(type="box", name_hint="Torso", dimensions={"length": 100, "width": 100, "height": 15}),
            CADFeature(type="fillet", dimensions={"radius": 3}, target_hint="Torso"),
        ],
    )
    result = select_recipe(spec)
    assert result["status"] == "llm_fallback"
    assert result["recipe"] is None


def test_should_use_recipe_queue_false_when_phases_richer():
    from app.abstract_steps.planner import should_use_recipe_queue

    cad_spec = {"model_type": "robot", "features": [{"type": "box"}]}
    recipe_queue = {"steps": [{"step_id": "AS1"}, {"step_id": "AS2"}]}
    high_level_plan = {"phases": [{"phase_id": f"P{i}"} for i in range(1, 6)]}
    assert should_use_recipe_queue(cad_spec, {"recipe_id": "x"}, recipe_queue, high_level_plan) is False


def test_resolve_target_name_from_comma_separated_hint():
    from app.abstract_steps.planner import tool_calls_for_abstract_step
    from app.cad_spec.schemas import CADFeature, CADSpec

    spec = CADSpec(
        model_type="box",
        features=[
            CADFeature(type="box", name_hint="Base", dimensions={"length": 100, "width": 60, "height": 20}),
            CADFeature(type="fillet", dimensions={"radius": 3}, target_hint="Torso, Head, Base"),
        ],
    )
    step = {
        "step_id": "AS2",
        "step_type": "apply_edge_feature",
        "intent": "Apply fillet",
    }
    calls = tool_calls_for_abstract_step(
        cad_spec=spec,
        abstract_step=step,
        impact_map={"target_objects": ["Torso, Head, Base"]},
        name_map={},
        call_prefix="AS2",
    )
    assert calls[0]["args"]["target"] == "Base"


def test_skip_failure_advances_abstract_step_queue():
    queue = build_queue_from_phases(
        [
            {"phase_id": "P1", "intent": "a"},
            {"phase_id": "P2", "intent": "b"},
        ]
    ).model_dump(mode="json")
    state = {
        "session_id": "s1",
        "user_input": "test",
        "high_level_plan": {"phases": [{"phase_id": "P1"}, {"phase_id": "P2"}]},
        "current_phase_id": "P1",
        "last_tool_call": {"call_id": "P1_S1", "tool": "add_fillet", "args": {"target": "Missing"}},
        "execution_result": {"status": "error", "message": "Object not found: Missing"},
        "document_state": DocumentState(document_name="doc", objects=[]),
        "before_state": DocumentState(document_name="doc", objects=[]),
        "execution_history": {
            "recent": [
                {"status": "error"},
                {"status": "error"},
                {"status": "error"},
            ]
        },
        "abstract_step_queue": queue,
        "current_abstract_step": queue["steps"][0],
    }
    result = evaluate_step_node(state)["evaluate_result"]
    assert result["decision"] == "continue"
    assert result["current_abstract_step"]["step_id"] == "P2"


def test_recipe_selection_expands_abstract_steps():
    spec = generate_cad_spec("create a 100x60x20 box with fillet radius 3").cad_spec
    result = select_recipe(spec)
    assert result["status"] == "ok"
    assert result["recipe"]["recipe_id"] == "box_with_fillet_recipe"
    assert len(result["abstract_step_queue"]["steps"]) == 2
    assert "tool_calls" not in result["recipe"]


def test_next_step_for_current_abstract_step_is_bounded():
    spec = generate_cad_spec("create a 100x60x20 box").cad_spec
    recipe_result = select_recipe(spec)
    step = recipe_result["abstract_step_queue"]["steps"][0]
    calls = tool_calls_for_abstract_step(cad_spec=spec, abstract_step=step, call_prefix=step["step_id"])
    assert 1 <= len(calls) <= 3
    assert calls[0]["tool"] == "create_box"
    assert calls[0]["call_id"] == "AS1_1"


def test_geometry_validators_return_error_codes():
    before = DocumentState(
        objects=[
            CADObject(
                name="Base",
                label="Base",
                type="Part::Box",
                visible=True,
                topology=TopologySummary(solids=1, is_valid=True, volume=100.0),
            )
        ]
    )
    after = DocumentState(
        objects=[
            CADObject(
                name="Base_Hole",
                label="Base_Hole",
                type="Part::Feature",
                visible=True,
                topology=TopologySummary(solids=1, is_valid=True, volume=80.0),
            ),
            CADObject(
                name="Base",
                label="Base",
                type="Part::Box",
                visible=False,
                topology=TopologySummary(solids=1, is_valid=True, volume=100.0),
            ),
        ]
    )
    results = run_geometry_validators(
        ["verify_object_exists", "verify_shape_valid", "verify_volume_decreased", "verify_source_hidden"],
        before_state=before,
        after_state=after,
        tool_call={"expected_effect": {"new_object": "Base_Hole"}},
        execution_result={"produced_objects": ["Base_Hole"], "source_objects": ["Base"]},
    )
    assert all(item["passed"] for item in results)
    failed = run_geometry_validators(
        ["verify_object_exists"],
        after_state=after,
        tool_call={"expected_effect": {"new_object": "Missing"}},
        execution_result={},
    )
    assert failed[0]["passed"] is False
    assert failed[0]["error_code"] == "OBJECT_NOT_FOUND"


def test_advance_step_queue_moves_to_next_abstract_step():
    recipe = select_recipe(generate_cad_spec("create a 100x60x20 box with fillet radius 3").cad_spec)
    queue = AbstractStepQueue(**recipe["abstract_step_queue"])
    updated = advance_step_queue(queue, "AS1")
    assert updated.current_step_id == "AS2"
    assert updated.steps[0].status == "completed"
    assert updated.steps[1].status == "pending"


def test_should_advance_requires_successful_execution():
    assert should_advance_abstract_step(
        execution_passed=False,
        validator_results=[{"passed": True}],
    ) is False
    assert should_advance_abstract_step(
        execution_passed=True,
        validator_results=[{"passed": True}, {"passed": True}],
    ) is True
    assert should_advance_abstract_step(
        execution_passed=True,
        validator_results=[{"passed": False, "error_code": "SHAPE_INVALID"}],
    ) is False


def test_apply_abstract_step_advancement_returns_next_step():
    recipe = select_recipe(generate_cad_spec("create a 100x60x20 box with fillet radius 3").cad_spec)
    result = apply_abstract_step_advancement(recipe["abstract_step_queue"], "AS1")
    assert result["current_abstract_step"]["step_id"] == "AS2"
    assert result["queue_completed"] is False


def test_is_harness_session_requires_non_empty_queue():
    queue = {"steps": [{"step_id": "AS1", "status": "pending"}]}
    assert is_harness_session(None, queue) is True
    assert is_harness_session({"model_type": "box"}, queue) is True
    assert is_harness_session(None, None) is False
    assert is_harness_session({"model_type": "box"}, {"steps": []}) is False


def test_build_queue_from_phases_unifies_control():
    phases = [
        {"phase_id": "P1", "title": "body", "intent": "Create chassis", "success_criteria": []},
        {"phase_id": "P2", "title": "wheels", "intent": "Add wheels", "success_criteria": []},
    ]
    queue = build_queue_from_phases(phases)
    assert queue.recipe_id == "llm_session"
    assert [step.step_id for step in queue.steps] == ["P1", "P2"]
    assert queue.steps[0].step_type == "llm_phase"
    assert "verify_object_exists" in queue.steps[0].postconditions


def test_resolve_validator_names_defaults_on_llm_path():
    names = resolve_validator_names({"postconditions": []}, None)
    assert names == ["verify_object_exists", "verify_shape_valid"]


def test_llm_spec_used_for_open_requirement(monkeypatch):
    from app.cad_spec.schemas import CADFeature, CADSpec, SpecGenerationResult
    import app.cad_spec.generator as generator_module

    def fake_llm(user_input):
        return SpecGenerationResult(
            status="ok",
            user_input=user_input,
            cad_spec=CADSpec(
                model_type="car",
                features=[
                    CADFeature(type="body", name_hint="Body", dimensions={"length": 400}),
                    CADFeature(type="wheel", name_hint="Wheel", dimensions={"radius": 30}),
                ],
            ),
        )

    monkeypatch.setattr("app.llm.llm_provider.generate_cad_spec_with_llm", fake_llm)
    result = generate_cad_spec("生成一辆现代化小汽车")
    assert result.status == "ok"
    assert result.cad_spec.model_type == "car"
    assert len(result.cad_spec.features) == 2


def test_evaluate_runs_default_validators_without_recipe():
    before = DocumentState(document_name="doc", objects=[])
    after = DocumentState(
        document_name="doc",
        objects=[
            CADObject(
                name="Base",
                label="Base",
                type="Part::Box",
                visible=True,
                topology=TopologySummary(solids=1, is_valid=True, volume=120000.0),
            )
        ],
    )
    queue = build_queue_from_phases([{"phase_id": "P1", "intent": "box"}]).model_dump(mode="json")
    current_step = queue["steps"][0]
    state = {
        "session_id": "s1",
        "user_input": "box",
        "high_level_plan": {"phases": [{"phase_id": "P1", "intent": "box"}]},
        "current_phase_id": "P1",
        "last_tool_call": {"call_id": "P1_S1", "tool": "create_box"},
        "execution_result": {"status": "success", "produced_objects": ["Base"]},
        "document_state": after,
        "before_state": before,
        "execution_history": {"recent": []},
        "abstract_step_queue": queue,
        "current_abstract_step": current_step,
    }
    result = evaluate_step_node(state)
    eval_result = result["evaluate_result"]
    assert eval_result["validator_results"]
    assert all(item["passed"] for item in eval_result["validator_results"])


def test_plan_next_step_uses_llm_for_llm_phase_step(monkeypatch):
    import app.graph.nodes as nodes

    captured = {}

    def fake_next(**kwargs):
        captured["current_phase_id"] = kwargs.get("current_phase_id")
        return {
            "decision": "execute",
            "phase_id": kwargs.get("current_phase_id"),
            "tool_calls": [{"call_id": "P1_S1", "tool": "create_box", "args": {"name": "Base"}}],
            "message": "llm",
        }

    monkeypatch.setattr(nodes, "generate_next_tool_calls", fake_next)

    queue = build_queue_from_phases([{"phase_id": "P1", "intent": "box"}]).model_dump(mode="json")
    state = {
        "user_input": "box",
        "high_level_plan": {"phases": [{"phase_id": "P1", "intent": "box"}]},
        "current_phase_id": "P1",
        "document_state": DocumentState(document_name="doc"),
        "execution_history": {"recent": []},
        "name_map": {},
        "cad_spec": {"model_type": "box", "features": []},
        "abstract_step_queue": queue,
        "current_abstract_step": queue["steps"][0],
    }
    result = plan_next_step_node(state)
    assert result["next_step_result"]["message"] == "llm"
    assert captured["current_phase_id"] == "P1"


def test_plan_next_step_falls_back_to_llm_without_harness(monkeypatch):
    import app.graph.nodes as nodes

    captured = {}

    def fake_next(**kwargs):
        captured.update(kwargs)
        return {"decision": "execute", "phase_id": "P1", "tool_calls": [], "message": "llm"}

    monkeypatch.setattr(nodes, "generate_next_tool_calls", fake_next)

    state = {
        "user_input": "modern car",
        "high_level_plan": {"phases": [{"phase_id": "P1", "intent": "body"}]},
        "current_phase_id": "P1",
        "document_state": DocumentState(document_name="doc"),
        "execution_history": {"recent": []},
        "name_map": {},
        "cad_spec": None,
        "abstract_step_queue": None,
        "current_abstract_step": None,
    }
    result = plan_next_step_node(state)
    assert result["next_step_result"]["message"] == "llm"
    assert captured["current_phase_id"] == "P1"


def test_plan_next_step_finishes_when_harness_queue_exhausted():
    spec = generate_cad_spec("create a 100x60x20 box").cad_spec
    recipe = select_recipe(spec)
    queue = recipe["abstract_step_queue"]
    queue["current_step_id"] = None
    for step in queue["steps"]:
        step["status"] = "completed"

    state = {
        "user_input": "create a box",
        "high_level_plan": {"phases": [{"phase_id": "P1", "intent": "box"}]},
        "current_phase_id": "P1",
        "document_state": DocumentState(document_name="doc"),
        "execution_history": {"recent": []},
        "name_map": {},
        "cad_spec": spec.model_dump(mode="json"),
        "impact_map": build_impact_map(spec, DocumentState(document_name="doc")).model_dump(mode="json"),
        "current_recipe": recipe["recipe"],
        "abstract_step_queue": queue,
        "current_abstract_step": None,
    }
    result = plan_next_step_node(state)
    assert result["next_step_result"]["decision"] == "finish"


def test_evaluate_step_advances_abstract_step_on_success():
    spec = generate_cad_spec("create a 100x60x20 box with fillet radius 3").cad_spec
    recipe = select_recipe(spec)
    current_step = recipe["abstract_step_queue"]["steps"][0]
    before = DocumentState(document_name="doc", objects=[])
    after = DocumentState(
        document_name="doc",
        objects=[
            CADObject(
                name="Base",
                label="Base",
                type="Part::Box",
                visible=True,
                topology=TopologySummary(solids=1, is_valid=True, volume=120000.0),
            )
        ],
    )
    state = {
        "session_id": "s1",
        "user_input": "box with fillet",
        "high_level_plan": {"phases": [{"phase_id": "P1", "intent": "box"}]},
        "current_phase_id": "P1",
        "last_tool_call": {"call_id": "AS1_1", "tool": "create_box"},
        "execution_result": {
            "status": "success",
            "produced_objects": ["Base"],
            "source_objects": [],
        },
        "document_state": after,
        "before_state": before,
        "execution_history": {"recent": []},
        "cad_spec": spec.model_dump(mode="json"),
        "current_recipe": recipe["recipe"],
        "abstract_step_queue": recipe["abstract_step_queue"],
        "current_abstract_step": current_step,
    }
    result = evaluate_step_node(state)
    eval_result = result["evaluate_result"]
    assert eval_result["decision"] == "continue"
    assert eval_result["current_abstract_step"]["step_id"] == "AS2"
    assert eval_result["abstract_step_queue"]["current_step_id"] == "AS2"


def test_harness_api_spec_to_recipe_flow():
    spec_resp = client.post("/agent/spec", json={"user_input": "create a 100x60x20 box with fillet radius 3"})
    assert spec_resp.status_code == 200
    cad_spec = spec_resp.json()["cad_spec"]

    impact_resp = client.post(
        "/agent/impact_map",
        json={"cad_spec": cad_spec, "document_state": {"document_name": "doc", "objects": []}},
    )
    assert impact_resp.status_code == 200
    assert impact_resp.json()["status"] == "ok"

    recipe_resp = client.post(
        "/agent/select_recipe",
        json={"cad_spec": cad_spec, "impact_map": impact_resp.json()["impact_map"]},
    )
    assert recipe_resp.status_code == 200
    body = recipe_resp.json()
    assert body["status"] == "ok"
    assert body["recipe"]["recipe_id"] == "box_with_fillet_recipe"
    assert len(body["abstract_step_queue"]["steps"]) == 2


def test_replay_trace_validates_harness_session():
    import tempfile

    session_dir = Path(tempfile.mkdtemp(prefix="v08_replay_"))
    step_dir = session_dir / "001_spec"
    step_dir.mkdir(parents=True)
    summary = {
        "session_id": "session_test",
        "steps": [{"step_name": "001_spec", "endpoint": "spec"}],
    }
    (session_dir / "session_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (step_dir / "api_response.json").write_text(
        json.dumps({"status": "ok", "cad_spec": {"model_type": "box"}}),
        encoding="utf-8",
    )

    result = replay_trace(session_dir)
    assert result["status"] == "ok"
    assert result["issues"] == []


if __name__ == "__main__":
    test_cad_spec_has_no_tool_calls()
    test_impact_map_blocks_high_risk_without_target()
    test_recipe_selection_expands_abstract_steps()
    test_next_step_for_current_abstract_step_is_bounded()
    test_geometry_validators_return_error_codes()
    test_is_harness_session_requires_spec_and_queue()
    test_advance_step_queue_moves_to_next_abstract_step()
    test_should_advance_requires_successful_execution()
    test_apply_abstract_step_advancement_returns_next_step()
    test_plan_next_step_finishes_when_harness_queue_exhausted()
    test_evaluate_step_advances_abstract_step_on_success()
    test_harness_api_spec_to_recipe_flow()
    test_replay_trace_validates_harness_session(Path("."))
    print("V0.8 CAD Harness tests passed")
