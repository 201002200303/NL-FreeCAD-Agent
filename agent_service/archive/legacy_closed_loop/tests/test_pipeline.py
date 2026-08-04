"""Legacy plan pipeline validation (LangGraph removed; now plain functions)."""

from app.workflow.service import _validate_plan, should_end, legacy_plan

print("=" * 50)
print("TEST 1: validate correct plan")
print("=" * 50)
good_plan = {
    "status": "ok",
    "goal": "test",
    "plan": [
        {
            "step_id": "step_1",
            "tool": "create_box",
            "args": {"name": "TestBox", "length": 100, "width": 60, "height": 20},
            "depends_on": [],
        }
    ],
}
assert _validate_plan(good_plan) == []
print("  PASS")

print("TEST 2: unknown tool is rejected")
bad_tool_plan = {
    "status": "ok",
    "goal": "test",
    "plan": [{"step_id": "step_1", "tool": "make_sphere", "args": {"name": "Ball", "radius": 10}}],
}
errors = _validate_plan(bad_tool_plan)
assert errors and "未知工具" in errors[0]
print("  PASS")

print("TEST 3: missing required params")
missing_param_plan = {
    "status": "ok",
    "goal": "test",
    "plan": [{"step_id": "step_1", "tool": "create_box", "args": {"name": "Box1", "length": 100}}],
}
assert len(_validate_plan(missing_param_plan)) == 2
print("  PASS")

print("TEST 4: wrong arg type")
type_error_plan = {
    "status": "ok",
    "goal": "test",
    "plan": [{"step_id": "step_1", "tool": "create_box", "args": {"name": "Box1", "length": "abc", "width": 60, "height": 20}}],
}
assert any("期望类型 float" in e for e in _validate_plan(type_error_plan))
print("  PASS")

print("TEST 5-7: retry routing")
assert should_end({"status": "ok", "retry_count": 0}) == "end"
assert should_end({"status": "validation_failed", "retry_count": 0}) == "retry"
assert should_end({"status": "validation_failed", "retry_count": 2}) == "end"
print("  PASS")

print("TEST 8: legacy_plan runs without a graph framework")
result = legacy_plan(user_input="create a 100x60x20mm box", document_state=None)
assert result["status"] in {"ok", "need_more_info", "validation_failed", "error"}
assert "retry_count" in result
print("  PASS")

print("ALL TESTS PASSED")
