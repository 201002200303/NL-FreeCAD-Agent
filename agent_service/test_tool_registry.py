"""V0.6+ tests: tool registry, category retrieval, alignment."""
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


def test_tool_count():
    assert len(TOOL_SPECS) == 53, f"Expected 53 tools, got {len(TOOL_SPECS)}"
    all_categorized = sum(len(c["tools"]) for c in TOOL_CATEGORIES.values())
    assert all_categorized == 53
    assert "mirror" not in TOOL_SPECS
    for name in ("sketch_add_arc", "sketch_add_polyline", "sketch_add_bspline"):
        assert name in TOOL_SPECS
        assert get_category_for_tool(name) == "sketch"
    for name in ("align_objects", "place_relative", "copy_object"):
        assert get_category_for_tool(name) == "transform"
    for name in ("polar_pattern", "linear_pattern", "distribute_along"):
        assert get_category_for_tool(name) == "pattern"
    assert get_category_for_tool("cut_hole") == "boolean"


def test_category_retrieval():
    prim = get_tools_by_categories(["primitives"])
    assert set(prim.keys()) == set(TOOL_CATEGORIES["primitives"]["tools"])
    assert "create_sphere" in prim
    assert "boolean_fuse" not in prim

    multi = get_tools_by_categories(["primitives", "features"])
    assert "create_box" in multi
    assert "add_fillet" in multi
    assert "mirror" not in multi
    assert "cut_hole" not in multi  # now under boolean
    assert len(multi) == 7  # 5 primitives + 2 features


def test_category_inference():
    cats = infer_categories_for_task("创建一个台灯，需要底座和倒圆角")
    assert "primitives" in cats or "features" in cats

    simple = infer_categories_for_task("创建一个球")
    assert "primitives" in simple

    broad = infer_categories_for_task("随便做个东西")
    # 有界 fallback，不再回退到全部类别
    assert 0 < len(broad) < len(TOOL_CATEGORIES)


def test_prompt_subset_size():
    full = _build_tools_description()
    subset = _build_tools_description(
        resolve_tool_specs_for_prompt(["primitives"], include_core=False)
    )
    assert len(subset) < len(full)
    assert "create_sphere" in subset
    assert "boolean_fuse" not in subset


def test_category_summary():
    summary = get_category_summary(["primitives", "export"])
    assert "primitives" in summary
    assert "export" in summary
    assert "assembly" not in summary


def test_list_tool_names_matches_specs():
    assert set(list_tool_names()) == set(TOOL_SPECS.keys())


def test_reverse_lookup():
    assert get_category_for_tool("create_box") == "primitives"
    assert get_category_for_tool("boolean_cut") == "boolean"
    assert get_category_for_tool("not_a_tool") is None


def test_build_tools_description_headers():
    text = build_tools_description(resolve_tool_specs_for_prompt(["query"], include_core=False))
    assert "### get_object_detail" in text
    assert "### create_box" not in text
