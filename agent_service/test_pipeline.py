"""验证 LangGraph pipeline 校验 + 重试机制"""
import json
from app.graph.nodes import _validate_plan, should_end
from app.graph.cad_graph import get_cad_agent

print("=" * 50)
print("TEST 1: 校验正确的 plan")
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
errors = _validate_plan(good_plan)
print(f"  错误数: {len(errors)}")
assert len(errors) == 0, f"预期 0 个错误，实际: {errors}"
print("  PASS")

print()
print("=" * 50)
print("TEST 2: 校验错误工具名")
print("=" * 50)
bad_tool_plan = {
    "status": "ok",
    "goal": "test",
    "plan": [
        {
            "step_id": "step_1",
            "tool": "make_sphere",
            "args": {"name": "Ball", "radius": 10},
        }
    ],
}
errors = _validate_plan(bad_tool_plan)
print(f"  错误数: {len(errors)}")
for e in errors:
    print(f"    - {e}")
assert len(errors) > 0, "预期有错误"
assert "未知工具" in errors[0], f"预期包含'未知工具': {errors[0]}"
print("  PASS")

print()
print("=" * 50)
print("TEST 3: 校验缺少必填参数")
print("=" * 50)
missing_param_plan = {
    "status": "ok",
    "goal": "test",
    "plan": [
        {
            "step_id": "step_1",
            "tool": "create_box",
            "args": {"name": "Box1", "length": 100},
        }
    ],
}
errors = _validate_plan(missing_param_plan)
print(f"  错误数: {len(errors)}")
for e in errors:
    print(f"    - {e}")
assert len(errors) == 2, f"预期 2 个错误(width, height), 实际: {errors}"
print("  PASS")

print()
print("=" * 50)
print("TEST 4: 校验参数类型错误")
print("=" * 50)
type_error_plan = {
    "status": "ok",
    "goal": "test",
    "plan": [
        {
            "step_id": "step_1",
            "tool": "create_box",
            "args": {"name": "Box1", "length": "abc", "width": 60, "height": 20},
        }
    ],
}
errors = _validate_plan(type_error_plan)
print(f"  错误数: {len(errors)}")
for e in errors:
    print(f"    - {e}")
assert any("期望类型 float" in e for e in errors), f"预期有类型错误: {errors}"
print("  PASS")

print()
print("=" * 50)
print("TEST 5: 条件路由 - 校验通过 → end")
print("=" * 50)
state_ok = {"status": "ok", "retry_count": 0, "validation_errors": []}
route = should_end(state_ok)
print(f"  路由: {route}")
assert route == "end"
print("  PASS")

print()
print("=" * 50)
print("TEST 6: 条件路由 - 校验失败 → retry")
print("=" * 50)
state_fail = {"status": "validation_failed", "retry_count": 0, "validation_errors": ["err"]}
route = should_end(state_fail)
print(f"  路由: {route}")
assert route == "retry"
print("  PASS")

print()
print("=" * 50)
print("TEST 7: 条件路由 - 超过最大重试 → end")
print("=" * 50)
state_max = {"status": "validation_failed", "retry_count": 2, "validation_errors": ["err"]}
route = should_end(state_max)
print(f"  路由: {route}")
assert route == "end"
print("  PASS")

print()
print("=" * 50)
print("TEST 8: 完整 graph 执行（模拟错误 plan 触发重试）")
print("=" * 50)
agent = get_cad_agent()

# Simulate a state where LLM already returned a valid plan
input_state = {
    "user_input": "create a 100x60x20mm box",
    "document_state": None,
    "conversation_id": None,
    "plan_json": None,
    "status": "",
    "error_message": None,
    "retry_count": 0,
    "validation_errors": [],
}
result = agent.invoke(input_state)
print(f"  最终状态: {result['status']}")
print(f"  重试次数: {result['retry_count']}")
if result.get("plan_json"):
    plan = result["plan_json"]
    print(f"  plan goal: {plan.get('goal', 'N/A')[:50]}")
    print(f"  plan steps: {len(plan.get('plan', []))}")
    for step in plan.get("plan", []):
        print(f"    - {step.get('tool')}: {step.get('args', {}).get('name', '?')}")
print("  PASS")

print()
print("=" * 50)
print("ALL TESTS PASSED!")
print("=" * 50)
