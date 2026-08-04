"""V0.6 tests: tool registry, category retrieval, validation alignment."""
from app.tools.tool_specs import TOOL_SPECS, list_tool_names
from app.tools.tool_registry import (
    TOOL_CATEGORIES,
    build_tools_description,
    get_category_for_tool,
    get_category_summary,
    get_tools_by_categories,
    infer_categories_for_task,
    resolve_tool_specs_for_prompt,
    validate_registry_alignment,
)
from app.llm.llm_provider import _build_tools_description


def test_registry_alignment():
    errors = validate_registry_alignment()
    assert errors == [], f"Registry alignment errors: {errors}"
    print("  PASS: registry alignment")


def test_tool_count():
    assert len(TOOL_SPECS) == 53, f"Expected 53 tools, got {len(TOOL_SPECS)}"
    all_categorized = sum(len(c["tools"]) for c in TOOL_CATEGORIES.values())
    assert all_categorized == 53
    print("  PASS: 53 tools in specs and categories")
    assert "mirror" not in TOOL_SPECS
    for name in ("sketch_add_arc", "sketch_add_polyline", "sketch_add_bspline"):
        assert name in TOOL_SPECS
        assert get_category_for_tool(name) == "sketch"
    for name in (
        "align_objects", "place_relative", "distribute_along",
        "polar_pattern", "linear_pattern", "copy_object",
    ):
        assert name in TOOL_SPECS
        assert get_category_for_tool(name) == "transform"


def test_category_retrieval():
    prim = get_tools_by_categories(["primitives"])
    assert set(prim.keys()) == set(TOOL_CATEGORIES["primitives"]["tools"])
    assert "create_sphere" in prim
    assert "boolean_fuse" not in prim
    print("  PASS: category retrieval (primitives only)")

    multi = get_tools_by_categories(["primitives", "features"])
    assert "create_box" in multi
    assert "add_fillet" in multi
    assert "mirror" not in multi
    assert len(multi) == 8
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
    full = _build_tools_description()
    subset = _build_tools_description(
        resolve_tool_specs_for_prompt(["primitives"], allow_subset=True)
    )
    assert len(subset) < len(full)
    assert "create_sphere" in subset
    assert "boolean_fuse" not in subset
    print("  PASS: prompt subset smaller than full prompt")


def test_category_summary():
    summary = get_category_summary()
    assert "primitives" in summary
    assert "create_box" in summary
    print("  PASS: category summary for decomposer")


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
    test_reverse_lookup()
    print()
    print(f"All tools: {list_tool_names()}")
    print("=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)
