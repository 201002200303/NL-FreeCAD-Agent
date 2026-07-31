"""V0.6 tests: tool registry, category retrieval, validation alignment."""
from app.tools.tool_specs import TOOL_SPECS, list_tool_names
from app.tools.tool_registry import (
    TOOL_CATEGORIES,
    build_tools_description,
    get_category_for_tool,
    get_category_summary,
    get_tools_by_categories,
    infer_categories_for_task,
    validate_registry_alignment,
)
from app.graph.nodes import _validate_plan
from app.llm.llm_provider import build_system_prompt


def test_registry_alignment():
    errors = validate_registry_alignment()
    assert errors == [], f"Registry alignment errors: {errors}"
    print("  PASS: registry alignment")


def test_tool_count():
    assert len(TOOL_SPECS) == 49, f"Expected 49 tools, got {len(TOOL_SPECS)}"
    all_categorized = sum(len(c["tools"]) for c in TOOL_CATEGORIES.values())
    assert all_categorized == 49
    print("  PASS: 49 tools in specs and categories")
    for name in ("sketch_add_arc", "sketch_add_polyline", "sketch_add_bspline"):
        assert name in TOOL_SPECS
        assert get_category_for_tool(name) == "sketch"


def test_category_retrieval():
    prim = get_tools_by_categories(["primitives"])
    assert set(prim.keys()) == set(TOOL_CATEGORIES["primitives"]["tools"])
    assert "create_sphere" in prim
    assert "boolean_fuse" not in prim
    print("  PASS: category retrieval (primitives only)")

    multi = get_tools_by_categories(["primitives", "features"])
    assert "create_box" in multi
    assert "add_fillet" in multi
    assert len(multi) == 9
    print("  PASS: multi-category retrieval")


def test_category_inference():
    cats = infer_categories_for_task("创建一个台灯，需要底座和倒圆角")
    assert "primitives" in cats
    assert "features" in cats
    print(f"  PASS: category inference -> {cats}")

    simple = infer_categories_for_task("创建一个球")
    assert "primitives" in simple
    print("  PASS: simple task inference")

    broad = infer_categories_for_task("随便做个东西")
    assert len(broad) == len(TOOL_CATEGORIES)
    print("  PASS: unmatched task falls back to all categories")


def test_prompt_subset_size():
    full = build_system_prompt()
    subset = build_system_prompt(tool_categories=["primitives"])
    assert len(subset) < len(full)
    assert "create_sphere" in subset
    assert "boolean_fuse" not in subset
    print("  PASS: prompt subset smaller than full prompt")


def test_category_summary():
    summary = get_category_summary()
    assert "primitives" in summary
    assert "create_box" in summary
    print("  PASS: category summary for decomposer")


def test_validate_new_tools():
    plan = {
        "status": "ok",
        "goal": "test lamp",
        "plan": [
            {
                "step_id": "step_1",
                "tool": "create_sphere",
                "args": {"name": "Bulb", "radius": 15},
                "depends_on": [],
            },
            {
                "step_id": "step_2",
                "tool": "boolean_fuse",
                "args": {"name": "LampBody", "base": "Base", "tool": "Pole"},
                "depends_on": ["step_1"],
            },
            {
                "step_id": "step_3",
                "tool": "add_fillet",
                "args": {"target": "LampBody", "radius": 2},
                "depends_on": ["step_2"],
            },
        ],
    }
    errors = _validate_plan(plan)
    assert errors == [], f"Validation errors: {errors}"
    print("  PASS: validate plan with new tools")


def test_reverse_lookup():
    assert get_category_for_tool("create_box") == "primitives"
    assert get_category_for_tool("boolean_cut") == "boolean"
    assert get_category_for_tool("export_stl") == "export"
    print("  PASS: reverse category lookup")


if __name__ == "__main__":
    print("=" * 50)
    print("V0.6 Tool Registry Tests")
    print("=" * 50)
    test_registry_alignment()
    test_tool_count()
    test_category_retrieval()
    test_category_inference()
    test_prompt_subset_size()
    test_category_summary()
    test_validate_new_tools()
    test_reverse_lookup()
    print()
    print(f"All tools: {list_tool_names()}")
    print("=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)
