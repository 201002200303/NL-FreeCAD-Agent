"""Diagnose the 3 failing harness tests by mocking LLM with deterministic returns.

This distinguishes code-logic bugs (fail even with deterministic LLM) from
LLM-nondeterminism (pass when LLM returns what tests expect).
"""
import sys

sys.path.insert(0, ".")
import app.graph.nodes as nodes
from app.abstract_steps.planner import build_queue_from_phases, build_queue_from_high_level_plan
from app.cad_spec.generator import generate_cad_spec
from app.inspection.impact_map import build_impact_map
from app.recipes.registry import select_recipe
from app.schemas.cad_state import DocumentState, CADObject, TopologySummary


def _bbox(x0, x1, y0, y1, z0, z1):
    return {
        "xmin": x0, "xmax": x1, "ymin": y0, "ymax": y1,
        "zmin": z0, "zmax": z1,
        "center": [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2],
        "size": [x1 - x0, y1 - y0, z1 - z0],
    }


def run(name, state, fake_eval):
    nodes.evaluate_step_result = fake_eval
    try:
        result = nodes.evaluate_step_node(state)
        eval_result = result["evaluate_result"]
        print(f"--- {name} ---")
        print("  decision:", eval_result.get("decision"))
        print("  phase_status:", eval_result.get("phase_status"))
        print("  current_abstract_step:", (eval_result.get("current_abstract_step") or {}).get("step_id"))
        print("  abstract_step_completed:", eval_result.get("abstract_step_completed"))
        print("  queue_current:", (eval_result.get("abstract_step_queue") or {}).get("current_step_id"))
        print("  updated_current_phase_id:", eval_result.get("updated_current_phase_id"))
        return eval_result
    finally:
        pass


# ── Test 3 replica: box_with_fillet_recipe, execute AS1, expect continue to AS2 ──
def test3():
    spec = generate_cad_spec("create a 100x60x20 box with fillet radius 3").cad_spec
    recipe = select_recipe(spec)
    current_step = recipe["abstract_step_queue"]["steps"][0]
    before = DocumentState(document_name="doc", objects=[])
    after = DocumentState(
        document_name="doc",
        objects=[CADObject(name="Base", label="Base", type="Part::Box", visible=True,
                           topology=TopologySummary(solids=1, is_valid=True, volume=120000.0))],
    )
    state = {
        "session_id": "s1",
        "user_input": "box with fillet",
        "high_level_plan": {"phases": [{"phase_id": "P1", "intent": "box"}]},
        "current_phase_id": "P1",
        "last_tool_call": {"call_id": "AS1_1", "tool": "create_box"},
        "execution_result": {"status": "success", "produced_objects": ["Base"], "source_objects": []},
        "document_state": after,
        "before_state": before,
        "execution_history": {"recent": []},
        "cad_spec": spec.model_dump(mode="json"),
        "current_recipe": recipe["recipe"],
        "abstract_step_queue": recipe["abstract_step_queue"],
        "current_abstract_step": current_step,
    }
    def fake(**kwargs):
        return {"decision": "continue", "phase_status": "completed", "message": "ok", "repair_tool_calls": []}
    run("test3 (LLM returns continue/completed)", state, fake)


# ── Test 2 replica: strict validator warning, expect non-blocking advance ──
def test2():
    queue = build_queue_from_phases(
        [{"phase_id": "P1", "intent": "Add wheel"}, {"phase_id": "P2", "intent": "Add lights"}]
    ).model_dump(mode="json")
    current_step = queue["steps"][0]
    after = DocumentState(objects=[CADObject(name="Wheel_FL", label="Wheel_FL", type="Part::Feature",
                                             bbox=_bbox(0, 60, 0, 60, 0, 20))])
    state = {
        "session_id": "s1",
        "high_level_plan": {"phases": [{"phase_id": "P1"}, {"phase_id": "P2"}]},
        "current_phase_id": "P1",
        "last_tool_call": {"call_id": "P1_S1", "tool": "create_cylinder",
                           "expected_effect": {"new_object": "Wheel_FL", "validators": ["verify_orientation"],
                                               "orientation": {"object": "Wheel_FL", "expected_axis": "Y", "mode": "thin"}}},
        "execution_result": {"status": "success", "produced_objects": ["Wheel_FL"]},
        "document_state": after,
        "before_state": DocumentState(objects=[]),
        "execution_history": {"recent": []},
        "abstract_step_queue": queue,
        "current_abstract_step": current_step,
        "strict_validation": True,
    }
    def fake(**kwargs):
        return {"decision": "continue", "phase_status": "completed", "message": "ok", "repair_tool_calls": []}
    run("test2 (LLM returns continue/completed)", state, fake)


# ── Test 1 replica: execution error, skip-and-advance expectation ──
def test1():
    queue = build_queue_from_phases(
        [{"phase_id": "P1", "intent": "a"}, {"phase_id": "P2", "intent": "b"}]
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
        "execution_history": {"recent": [{"status": "error"}, {"status": "error"}, {"status": "error"}]},
        "abstract_step_queue": queue,
        "current_abstract_step": queue["steps"][0],
    }
    def fake(**kwargs):
        return {"decision": "skip_and_continue", "phase_status": "failed", "message": "skip", "repair_tool_calls": []}
    run("test1 (LLM returns skip_and_continue/failed)", state, fake)


test3()
test2()
test1()
