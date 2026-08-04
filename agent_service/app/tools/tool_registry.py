"""Tree-structured tool registry for category-based retrieval."""

from app.tools.tool_specs import TOOL_SPECS, get_tool_spec, list_tool_names

ALL_TOOL_CATEGORIES: list[str] = [
    "primitives",
    "boolean",
    "features",
    "transform",
    "export",
    "query",
    "sketch",
    "partdesign",
    "surface",
    "assembly",
]

TOOL_CATEGORIES: dict[str, dict] = {
    "primitives": {
        "label": "基础几何",
        "description": "创建立方体、圆柱、球体、圆锥、圆环等基本体",
        "tools": [
            "create_box", "create_cylinder", "create_sphere",
            "create_cone", "create_torus",
        ],
    },
    "boolean": {
        "label": "布尔运算",
        "description": "合并、切割、取交集",
        "tools": ["boolean_fuse", "boolean_cut", "boolean_common"],
    },
    "features": {
        "label": "特征操作",
        "description": "倒圆角、倒角、打孔",
        "tools": ["add_fillet", "add_chamfer", "cut_hole"],
    },
    "transform": {
        "label": "变换与修改",
        "description": "位置、移动、旋转、缩放、复制、圆周/线性阵列、参数修改、删除",
        "tools": [
            "set_placement", "move", "rotate", "scale", "copy_object",
            "polar_pattern", "linear_pattern",
            "align_objects", "place_relative", "distribute_along",
            "modify_param", "delete_object",
        ],
    },
    "export": {
        "label": "导出",
        "description": "保存文档、导出 STEP/STL",
        "tools": ["save_fcstd", "export_step", "export_stl"],
    },
    "query": {
        "label": "几何事实查询",
        "description": "查询文档摘要、对象详情、bbox 间隙、朝向和拓扑，空间操作前必用",
        "tools": [
            "summarize_document", "get_object_detail", "measure_gap",
            "compare_orientation", "list_topology",
        ],
    },
    "sketch": {
        "label": "草图",
        "description": "Body、草图创建、画线/矩形/圆、约束",
        "tools": [
            "create_body", "create_sketch", "create_sketch_on_face",
            "sketch_add_line", "sketch_add_rect", "sketch_add_circle",
            "sketch_add_arc", "sketch_add_polyline", "sketch_add_bspline",
            "sketch_add_constraint",
        ],
    },
    "partdesign": {
        "label": "特征链",
        "description": "Pad/Pocket/旋转/拉伸到面",
        "tools": [
            "pad_sketch", "pocket_sketch", "pad_to_face",
            "revolve_sketch", "extrude_sketch",
        ],
    },
    "surface": {
        "label": "曲面",
        "description": "放样、扫掠、旋转体",
        "tools": ["make_loft", "make_sweep", "make_revolve"],
    },
    "assembly": {
        "label": "装配",
        "description": "装配容器、加入零件、平面对齐/同轴配合",
        "tools": ["create_assembly", "add_to_assembly", "mate_planes", "mate_coaxial"],
    },
}

_TOOL_TO_CATEGORY: dict[str, str] = {}
for _cat, _info in TOOL_CATEGORIES.items():
    for _tool in _info["tools"]:
        _TOOL_TO_CATEGORY[_tool] = _cat


def get_all_tool_specs() -> dict:
    """Return the full registered tool spec map."""
    return dict(TOOL_SPECS)


def resolve_tool_specs_for_prompt(
    allowed_categories: list[str] | None = None,
    *,
    allow_subset: bool = False,
) -> dict:
    """Resolve which tool specs to inject into LLM prompts.

    Default policy: always expose the full registry. Category subsets are opt-in
    only (tests / explicit harness experiments).
    """
    if allow_subset and allowed_categories:
        return get_tools_by_categories(allowed_categories)
    return get_all_tool_specs()


def get_category_for_tool(tool_name: str) -> str | None:
    return _TOOL_TO_CATEGORY.get(tool_name)


def get_tools_by_categories(categories: list[str]) -> dict:
    result: dict = {}
    for cat in categories:
        info = TOOL_CATEGORIES.get(cat)
        if not info:
            continue
        for tool_name in info["tools"]:
            spec = get_tool_spec(tool_name)
            if spec:
                result[tool_name] = spec
    return result


def get_category_summary(categories: list[str] | None = None) -> str:
    lines = ["## 可用工具类别\n"]
    items = TOOL_CATEGORIES.items()
    if categories:
        allowed = set(categories)
        items = [(cat_id, info) for cat_id, info in items if cat_id in allowed]
    for cat_id, info in items:
        tool_list = ", ".join(f"`{t}`" for t in info["tools"])
        lines.append(f"- **{cat_id}** ({info['label']}): {info['description']}")
        lines.append(f"  工具: {tool_list}\n")
    return "\n".join(lines)


def build_tools_description(tool_specs: dict | None = None) -> str:
    specs = tool_specs if tool_specs is not None else TOOL_SPECS
    lines = ["## 可用的建模工具\n"]
    for tool_name, tool_spec in specs.items():
        lines.append(f"### {tool_name}")
        lines.append(f"**描述**: {tool_spec['description']}")
        lines.append("**参数**:")
        for param_name, param_info in tool_spec["parameters"].items():
            required = "✓ 必需" if param_name in tool_spec.get("required", []) else "可选"
            param_type = param_info.get("type", "any")
            param_desc = param_info.get("description", "")
            default = param_info.get("default", "")
            default_str = f"，默认值: {default}" if default != "" and default is not None else ""
            lines.append(f"  - `{param_name}` ({param_type}, {required}): {param_desc}{default_str}")
        lines.append("")
    return "\n".join(lines)


def validate_registry_alignment() -> list[str]:
    errors: list[str] = []
    categorized = set(_TOOL_TO_CATEGORY.keys())
    spec_keys = set(TOOL_SPECS.keys())
    missing_in_categories = spec_keys - categorized
    missing_in_specs = categorized - spec_keys
    if missing_in_categories:
        errors.append(f"TOOL_SPECS 未分类: {sorted(missing_in_categories)}")
    if missing_in_specs:
        errors.append(f"分类中存在但未定义 spec: {sorted(missing_in_specs)}")
    return errors


def infer_categories_for_task(task_description: str) -> list[str]:
    text = task_description.lower()
    categories: list[str] = []

    keyword_map = {
        "primitives": [
            "box", "cube", "长方体", "cylinder", "圆柱", "sphere", "球",
            "cone", "圆锥", "torus", "圆环", "底座", "平台",
        ],
        "boolean": ["合并", "fuse", "union", "cut", "切割", "布尔", "交集", "common"],
        "features": ["倒角", "fillet", "chamfer", "圆角", "打孔", "hole"],
        "transform": [
            "移动", "move", "旋转", "rotate", "缩放", "scale", "复制", "copy",
            "位置", "placement", "对齐", "align", "相对", "distribute", "排列",
            "阵列", "pattern", "polar", "圆周", "linear_pattern",
        ],
        "export": ["导出", "export", "step", "stl", "保存", "save"],
        "query": [
            "查询", "拓扑", "list_topology", "get_object_detail", "measure_gap",
            "compare_orientation", "边", "面", "edge", "face", "编号", "间隙", "gap",
        ],
        "sketch": [
            "草图", "sketch", "画", "矩形", "圆", "圆弧", "arc", "折线", "polyline",
            "样条", "bspline", "spline", "constraint", "约束",
        ],
        "partdesign": ["拉伸", "pad", "pocket", "切除", "特征", "partdesign", "body"],
        "surface": ["放样", "loft", "扫掠", "sweep", "pipe", "旋转体", "revolve"],
        "assembly": ["装配", "assembly", "配合", "mate", "同轴", "对齐"],
    }

    for cat, keywords in keyword_map.items():
        if any(kw in text for kw in keywords):
            categories.append(cat)

    return categories or list(ALL_TOOL_CATEGORIES)
