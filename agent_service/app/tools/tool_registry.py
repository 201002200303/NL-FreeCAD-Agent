"""Tree-structured tool registry for category-based retrieval."""

from app.tools.tool_specs import TOOL_SPECS, get_tool_spec, list_tool_names

# 每轮 system prompt 始终注入完整 schema 的查询工具
CORE_TOOL_NAMES: tuple[str, ...] = (
    "summarize_document",
    "get_object_detail",
    "measure_gap",
)

ALL_TOOL_CATEGORIES: list[str] = [
    "primitives",
    "boolean",
    "features",
    "transform",
    "pattern",
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
            "create_cone", "create_torus", "create_wedge",
        ],
    },
    "boolean": {
        "label": "布尔与打孔",
        "description": "合并、切割、取交集、打孔",
        "tools": [
            "boolean_fuse", "boolean_cut", "boolean_common", "cut_hole",
        ],
    },
    "features": {
        "label": "精修特征",
        "description": "倒圆角、倒角",
        "tools": ["add_fillet", "add_chamfer"],
    },
    "transform": {
        "label": "变换与修改",
        "description": "位置、移动、旋转、缩放、复制、对齐、参数修改、删除",
        "tools": [
            "set_placement", "move", "rotate", "scale", "copy_object",
            "align_objects", "place_relative",
            "modify_param", "delete_object",
        ],
    },
    "pattern": {
        "label": "阵列",
        "description": "圆周阵列、线性阵列、等距分布",
        "tools": ["polar_pattern", "linear_pattern", "distribute_along"],
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
    categories: list[str] | tuple[str, ...] | None = None,
    *,
    include_core: bool = True,
) -> dict:
    """按类别解析要注入 prompt 的工具 schema。

    categories 为 None → 全量（兼容旧调用/调试）。
    给定 categories → 仅这些类别 + 可选 CORE 工具。
    """
    if not categories:
        return get_all_tool_specs()

    result = get_tools_by_categories(list(categories))
    if include_core:
        for name in CORE_TOOL_NAMES:
            spec = get_tool_spec(name)
            if spec:
                result[name] = spec
    return result


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
    """类别索引（名称 + 一句话 + 工具名列表）。categories=None 表示全部。"""
    lines = ["## 工具类别索引（完整 schema 仅见下方工作集）\n"]
    items = TOOL_CATEGORIES.items()
    if categories is not None:
        allowed = set(categories)
        items = [(cat_id, info) for cat_id, info in items if cat_id in allowed]
    for cat_id, info in items:
        lines.append(f"- **{cat_id}** ({info['label']}): {info['description']}")
    return "\n".join(lines)


def build_tools_description(tool_specs: dict | None = None) -> str:
    specs = tool_specs if tool_specs is not None else TOOL_SPECS
    lines = ["## 当前工具工作集（完整参数）\n"]
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
    """兼容旧测试：转发到 routing.route 的 tool_categories。"""
    from app.tools.routing import route

    return list(route(message=task_description).tool_categories)
