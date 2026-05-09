TOOL_SPECS: dict = {
    "create_box": {
        "description": "创建一个长方体 (Part::Box)",
        "parameters": {
            "name": {"type": "string", "description": "对象名称"},
            "length": {"type": "float", "description": "长度 (mm)"},
            "width": {"type": "float", "description": "宽度 (mm)"},
            "height": {"type": "float", "description": "高度 (mm)"},
            "unit": {"type": "string", "default": "mm"},
        },
        "required": ["name", "length", "width", "height"],
    },
    "create_cylinder": {
        "description": "创建一个圆柱体 (Part::Cylinder)",
        "parameters": {
            "name": {"type": "string", "description": "对象名称"},
            "radius": {"type": "float", "description": "半径 (mm)"},
            "height": {"type": "float", "description": "高度 (mm)"},
            "unit": {"type": "string", "default": "mm"},
        },
        "required": ["name", "radius", "height"],
    },
    "create_sketch": {
        "description": "创建一个草图 (Sketcher::SketchObject)",
        "parameters": {
            "name": {"type": "string", "description": "草图名称"},
            "plane": {"type": "string", "default": "XY", "description": "草图平面: XY, XZ, YZ"},
        },
        "required": ["name"],
    },
    "pad_sketch": {
        "description": "拉伸草图 (PartDesign::Pad)",
        "parameters": {
            "name": {"type": "string", "description": "结果对象名称"},
            "sketch": {"type": "string", "description": "草图对象名称"},
            "length": {"type": "float", "description": "拉伸长度 (mm)"},
        },
        "required": ["name", "sketch", "length"],
    },
    "cut_center_hole": {
        "description": "在目标中心创建通孔",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "hole_diameter": {"type": "float", "description": "孔径 (mm)"},
            "through_all": {"type": "bool", "default": True},
        },
        "required": ["target", "hole_diameter"],
    },
    "cut_corner_holes": {
        "description": "在目标四角创建通孔",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "hole_diameter": {"type": "float", "description": "孔径 (mm)"},
            "margin_x": {"type": "float", "description": "X 方向距边缘距离 (mm)"},
            "margin_y": {"type": "float", "description": "Y 方向距边缘距离 (mm)"},
            "through_all": {"type": "bool", "default": True},
        },
        "required": ["target", "hole_diameter", "margin_x", "margin_y"],
    },
    "add_fillet": {
        "description": "添加倒圆角",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "radius": {"type": "float", "description": "圆角半径 (mm)"},
            "edge_selector": {"type": "string", "default": "all", "description": "边选择器"},
        },
        "required": ["target", "radius"],
    },
    "add_chamfer": {
        "description": "添加倒角",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "size": {"type": "float", "description": "倒角尺寸 (mm)"},
            "edge_selector": {"type": "string", "default": "all"},
        },
        "required": ["target", "size"],
    },
    "modify_param": {
        "description": "修改对象参数",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "param": {"type": "string", "description": "参数名"},
            "value": {"type": "float", "description": "新值"},
        },
        "required": ["target", "param", "value"],
    },
    "delete_object": {
        "description": "删除对象",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
        },
        "required": ["target"],
    },
    "export_step": {
        "description": "导出为 STEP 文件",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "filepath": {"type": "string", "description": "导出路径"},
        },
        "required": ["target", "filepath"],
    },
    "export_stl": {
        "description": "导出为 STL 文件",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "filepath": {"type": "string", "description": "导出路径"},
            "tolerance": {"type": "float", "default": 0.1},
        },
        "required": ["target", "filepath"],
    },
    "save_fcstd": {
        "description": "保存 FreeCAD 文档",
        "parameters": {
            "filepath": {"type": "string", "description": "保存路径"},
        },
        "required": ["filepath"],
    },
}


def get_tool_spec(tool_name: str) -> dict | None:
    return TOOL_SPECS.get(tool_name)


def list_tool_names() -> list[str]:
    return list(TOOL_SPECS.keys())
