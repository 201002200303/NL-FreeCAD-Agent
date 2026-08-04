"""Tests for the batch-aware query-before-act policy.

Regression: when LLM emits a single batch like
  [create_sphere → A, scale A → B, create_box → C, boolean_cut(base=B, tool=C)]
the policy used to flag B as QUERY_REQUIRED (B not in doc yet), causing the
runtime to drop the whole batch and query a ghost object — leading to an
"Object not found" loop. The policy must now recognize B and C as produced
*earlier in the same batch* and skip the query requirement for them.
"""

from app.tools.query_policy import (
    validate_query_before_act,
    build_required_query_calls,
    extract_targets_from_call,
    _produced_names,
    _batch_producer_index,
)


def test_extract_targets_picks_all_reference_fields():
    call = {"tool": "boolean_cut", "args": {"name": "R", "base": "A", "tool": "B"}}
    assert extract_targets_from_call(call) == ["A", "B"]


def test_extract_targets_dedups():
    call = {"tool": "boolean_fuse", "args": {"name": "R", "base": "A", "tool": "A"}}
    assert extract_targets_from_call(call) == ["A"]


def test_produced_names_from_expected_effect():
    call = {
        "tool": "create_sphere",
        "args": {"name": "Mouse_Sphere", "radius": 60},
        "expected_effect": {"new_object": "Mouse_Sphere", "type": "Part::Sphere"},
    }
    assert _produced_names(call) == ["Mouse_Sphere"]


def test_produced_names_falls_back_to_args_name():
    call = {"tool": "create_box", "args": {"name": "Box1", "length": 10, "width": 10, "height": 10}}
    assert _produced_names(call) == ["Box1"]


def test_produced_names_uses_result_name_for_scale():
    call = {
        "tool": "scale",
        "args": {"target": "A", "scale_x": 1, "result_name": "B"},
    }
    assert _produced_names(call) == ["B"]


def test_produced_names_skips_query_tools():
    call = {"tool": "get_object_detail", "args": {"target": "A"}}
    assert _produced_names(call) == []


def test_batch_producer_index_is_strictly_prior():
    calls = [
        {"tool": "create_sphere", "args": {"name": "A"}},
        {"tool": "scale", "args": {"target": "A", "result_name": "B"}},
        {"tool": "create_box", "args": {"name": "C"}},
        {"tool": "boolean_cut", "args": {"name": "D", "base": "B", "tool": "C"}},
    ]
    idx = _batch_producer_index(calls)
    assert idx[0] == set()
    assert idx[1] == {"A"}
    assert idx[2] == {"A", "B"}
    assert idx[3] == {"A", "B", "C"}


def test_batch_with_create_then_boolean_does_not_require_query():
    """The exact scenario from session_d107267a that used to loop forever."""
    tool_calls = [
        {
            "call_id": "P1_S1",
            "tool": "create_sphere",
            "args": {"name": "Mouse_Sphere", "radius": 60, "pos_z": 19},
            "expected_effect": {"new_object": "Mouse_Sphere", "type": "Part::Sphere"},
        },
        {
            "call_id": "P1_S2",
            "tool": "scale",
            "args": {"target": "Mouse_Sphere", "scale_x": 1.0, "scale_y": 0.5, "scale_z": 0.32, "result_name": "Mouse_Body_Ellipsoid"},
            "expected_effect": {"new_object": "Mouse_Body_Ellipsoid", "type": "Part::Feature"},
        },
        {
            "call_id": "P1_S3",
            "tool": "create_box",
            "args": {"name": "Mouse_Cut_Box", "length": 200, "width": 100, "height": 10, "pos_z": -5},
            "expected_effect": {"new_object": "Mouse_Cut_Box", "type": "Part::Box"},
        },
        {
            "call_id": "P1_S4",
            "tool": "boolean_cut",
            "args": {"name": "Mouse_Body", "base": "Mouse_Body_Ellipsoid", "tool": "Mouse_Cut_Box"},
            "expected_effect": {"new_object": "Mouse_Body", "type": "Part::Feature"},
        },
    ]
    errors = validate_query_before_act(tool_calls, {"recent": []}, {"query_cache": {}})
    assert errors == [], f"expected no query errors, got: {errors}"


def test_boolean_on_unknown_existing_object_still_requires_query():
    """When the base is NOT produced in the batch and not in doc/cache, we still ask."""
    tool_calls = [
        {
            "call_id": "S1",
            "tool": "boolean_cut",
            "args": {"name": "R", "base": "ExistingA", "tool": "ExistingB"},
        },
    ]
    errors = validate_query_before_act(tool_calls, {"recent": []}, {"query_cache": {}})
    assert len(errors) == 2  # both base and tool are unknown
    targets = {e["target"] for e in errors}
    assert targets == {"ExistingA", "ExistingB"}


def test_boolean_on_document_object_skips_query():
    """Shaft_Chamfer already in document → boolean_cut must not QUERY_REQUIRED."""
    tool_calls = [
        {
            "call_id": "P3_S1",
            "tool": "create_box",
            "args": {"name": "Keyway_C", "length": 10, "width": 4, "height": 4},
        },
        {
            "call_id": "P3_S2",
            "tool": "boolean_cut",
            "args": {"name": "Shaft_Keyway", "base": "Shaft_Chamfer", "tool": "Keyway_C"},
        },
    ]
    doc = {"objects": [{"name": "Shaft_Chamfer", "type": "Part::Feature"}]}
    errors = validate_query_before_act(
        tool_calls, {"recent": []}, {"query_cache": {}}, document_state=doc
    )
    assert errors == [], f"expected no query errors, got: {errors}"


def test_cached_target_does_not_require_query():
    tool_calls = [
        {
            "call_id": "S1",
            "tool": "move",
            "args": {"target": "ExistingA"},
        },
    ]
    session_memory = {
        "query_cache": {
            "ExistingA": {
                "has_spatial_facts": True,
                "size": [10, 10, 10],
                "center": [0, 0, 0],
            }
        }
    }
    errors = validate_query_before_act(tool_calls, {"recent": []}, session_memory)
    assert errors == []


def test_build_required_query_calls_dedups():
    errors = [
        {"tool": "boolean_cut", "target": "A", "reason": "r"},
        {"tool": "boolean_cut", "target": "A", "reason": "r"},
        {"tool": "boolean_cut", "target": "B", "reason": "r"},
    ]
    calls = build_required_query_calls(errors)
    targets = [c["args"]["target"] for c in calls]
    assert targets == ["A", "B"]


def test_forward_reference_is_flagged():
    """If a call references a name produced LATER in the batch, that's a real
    error — we should NOT silently let it through (the object won't exist yet)."""
    tool_calls = [
        {
            "call_id": "S1",
            "tool": "boolean_cut",
            "args": {"name": "R", "base": "B", "tool": "C"},
        },
        {
            "call_id": "S2",
            "tool": "create_box",
            "args": {"name": "B"},
        },
    ]
    errors = validate_query_before_act(tool_calls, {"recent": []}, {"query_cache": {}})
    # B is produced later (not earlier), so it must still trigger a query.
    targets = {e["target"] for e in errors}
    assert "B" in targets
