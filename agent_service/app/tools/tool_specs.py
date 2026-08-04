"""Tool specifications for LLM plan generation.

Keep in sync with freecad_addon/AICADAgent/cad_tools/TOOL_REGISTRY.
"""

TOOL_SPECS: dict = {
    # ── primitives ──
    "create_box": {
        "description": (
            "创建长方体 (Part::Box)。"
            "默认 anchor=min：pos 是角点 (xmin,ymin,zmin)，盒子沿 +X/+Y/+Z 延伸。"
            "键槽/对称刀具请用 anchor=center：pos 为盒子中心。"
            "切勿把 min 模式的 pos_y=0 当成「关于 Y=0 对称」。"
        ),
        "parameters": {
            "name": {"type": "string", "description": "对象名称"},
            "length": {"type": "float", "description": "沿 X 长度 (mm)"},
            "width": {"type": "float", "description": "沿 Y 宽度 (mm)"},
            "height": {"type": "float", "description": "沿 Z 高度 (mm)"},
            "unit": {"type": "string", "default": "mm", "description": "单位，仅支持 mm"},
            "pos_x": {"type": "float", "default": 0, "description": "X (mm)；含义见 anchor"},
            "pos_y": {"type": "float", "default": 0, "description": "Y (mm)；含义见 anchor"},
            "pos_z": {"type": "float", "default": 0, "description": "Z (mm)；含义见 anchor"},
            "anchor": {
                "type": "string",
                "default": "min",
                "description": "min=角点放置（默认）；center=中心放置（键槽推荐）",
            },
        },
        "required": ["name", "length", "width", "height"],
    },
    "create_cylinder": {
        "description": "创建一个圆柱体 (Part::Cylinder)，默认轴沿 Z；支持位置与绕轴旋转",
        "parameters": {
            "name": {"type": "string", "description": "对象名称"},
            "radius": {"type": "float", "description": "半径 (mm)"},
            "height": {"type": "float", "description": "高度 (mm)"},
            "unit": {"type": "string", "default": "mm", "description": "单位，仅支持 mm"},
            "pos_x": {"type": "float", "default": 0, "description": "X 轴位置 (mm)，底面圆心"},
            "pos_y": {"type": "float", "default": 0, "description": "Y 轴位置 (mm)"},
            "pos_z": {"type": "float", "default": 0, "description": "Z 轴位置 (mm)"},
            "rot_x": {"type": "float", "default": 0, "description": "绕 X 轴旋转角度 (度)，如水平车轮用 90"},
            "rot_y": {"type": "float", "default": 0, "description": "绕 Y 轴旋转角度 (度)"},
            "rot_z": {"type": "float", "default": 0, "description": "绕 Z 轴旋转角度 (度)"},
        },
        "required": ["name", "radius", "height"],
    },
    "create_sphere": {
        "description": "创建一个球体 (Part::Sphere)，参考点为球心",
        "parameters": {
            "name": {"type": "string", "description": "对象名称"},
            "radius": {"type": "float", "description": "半径 (mm)"},
            "unit": {"type": "string", "default": "mm", "description": "单位，仅支持 mm"},
            "pos_x": {"type": "float", "default": 0, "description": "X 轴位置 (mm)"},
            "pos_y": {"type": "float", "default": 0, "description": "Y 轴位置 (mm)"},
            "pos_z": {"type": "float", "default": 0, "description": "Z 轴位置 (mm)"},
        },
        "required": ["name", "radius"],
    },
    "create_cone": {
        "description": "创建一个圆锥/圆台 (Part::Cone)，参考点为底面中心",
        "parameters": {
            "name": {"type": "string", "description": "对象名称"},
            "radius1": {"type": "float", "description": "底面半径 (mm)"},
            "radius2": {"type": "float", "description": "顶面半径 (mm)，0 为尖锥"},
            "height": {"type": "float", "description": "高度 (mm)"},
            "unit": {"type": "string", "default": "mm", "description": "单位，仅支持 mm"},
            "pos_x": {"type": "float", "default": 0, "description": "X 轴位置 (mm)"},
            "pos_y": {"type": "float", "default": 0, "description": "Y 轴位置 (mm)"},
            "pos_z": {"type": "float", "default": 0, "description": "Z 轴位置 (mm)"},
        },
        "required": ["name", "radius1", "radius2", "height"],
    },
    "create_torus": {
        "description": "创建一个圆环 (Part::Torus)",
        "parameters": {
            "name": {"type": "string", "description": "对象名称"},
            "radius1": {"type": "float", "description": "大圆半径 (mm)"},
            "radius2": {"type": "float", "description": "截面半径 (mm)"},
            "unit": {"type": "string", "default": "mm", "description": "单位，仅支持 mm"},
            "pos_x": {"type": "float", "default": 0, "description": "X 轴位置 (mm)"},
            "pos_y": {"type": "float", "default": 0, "description": "Y 轴位置 (mm)"},
            "pos_z": {"type": "float", "default": 0, "description": "Z 轴位置 (mm)"},
        },
        "required": ["name", "radius1", "radius2"],
    },
    # ── boolean ──
    "boolean_fuse": {
        "description": "布尔合并：将两个实体合并为一个 (Part::Feature)",
        "parameters": {
            "name": {"type": "string", "description": "结果对象名称"},
            "base": {"type": "string", "description": "基础对象名称"},
            "tool": {"type": "string", "description": "要合并的对象名称"},
        },
        "required": ["name", "base", "tool"],
    },
    "boolean_cut": {
        "description": "布尔切割：从 base 中减去 tool (Part::Feature)",
        "parameters": {
            "name": {"type": "string", "description": "结果对象名称"},
            "base": {"type": "string", "description": "被切割对象名称"},
            "tool": {"type": "string", "description": "切割工具对象名称"},
        },
        "required": ["name", "base", "tool"],
    },
    "boolean_common": {
        "description": "布尔交集：取两个实体的公共部分 (Part::Feature)",
        "parameters": {
            "name": {"type": "string", "description": "结果对象名称"},
            "base": {"type": "string", "description": "对象 A 名称"},
            "tool": {"type": "string", "description": "对象 B 名称"},
        },
        "required": ["name", "base", "tool"],
    },
    # ── features ──
    "add_fillet": {
        "description": "对目标实体边添加倒圆角",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "radius": {"type": "float", "description": "圆角半径 (mm)"},
            "edge_selector": {"type": "string", "default": "all", "description": "边选择: all/top/bottom/vertical/horizontal/longest/shortest/Edge1,Edge3/zone:+Z/face:Face3"},
            "face_selector": {"type": "string", "description": "限定在某个面的边: Face3 或 top/+Z 等"},
            "result_name": {"type": "string", "description": "结果对象名称（可选）"},
        },
        "required": ["target", "radius"],
    },
    "add_chamfer": {
        "description": "对目标实体边添加倒角",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "size": {"type": "float", "description": "倒角尺寸 (mm)"},
            "edge_selector": {"type": "string", "default": "all", "description": "边选择: all/top/bottom/vertical/horizontal/longest/shortest/Edge1,Edge3/zone:+Z/face:Face3"},
            "face_selector": {"type": "string", "description": "限定在某个面的边: Face3 或 top/+Z 等"},
            "result_name": {"type": "string", "description": "结果对象名称（可选）"},
        },
        "required": ["target", "size"],
    },
    "cut_hole": {
        "description": "在目标实体上打圆柱孔（默认在中心）。默认生成新对象 {target}_Hole，原对象隐藏",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "hole_diameter": {"type": "float", "description": "孔径 (mm)"},
            "through_all": {"type": "bool", "default": True, "description": "是否通孔"},
            "pos_x": {"type": "float", "description": "孔中心 X（可选，默认几何中心）"},
            "pos_y": {"type": "float", "description": "孔中心 Y（可选）"},
            "pos_z": {"type": "float", "description": "孔中心 Z（可选）"},
            "result_name": {"type": "string", "description": "结果对象名称（可选）"},
        },
        "required": ["target", "hole_diameter"],
    },
    "mirror": {
        "description": "镜像复制目标实体",
        "parameters": {
            "target": {"type": "string", "description": "源对象名称"},
            "name": {"type": "string", "description": "镜像结果对象名称"},
            "plane": {"type": "string", "default": "XY", "description": "镜像平面: XY, XZ, YZ"},
            "origin_x": {"type": "float", "default": 0},
            "origin_y": {"type": "float", "default": 0},
            "origin_z": {"type": "float", "default": 0},
        },
        "required": ["target", "name"],
    },
    # ── transform ──
    "set_placement": {
        "description": "设置对象的绝对位置和绕 X/Y/Z 轴旋转（度，非欧拉 YPR）",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "pos_x": {"type": "float", "default": 0, "description": "X 轴位置 (mm)"},
            "pos_y": {"type": "float", "default": 0, "description": "Y 轴位置 (mm)"},
            "pos_z": {"type": "float", "default": 0, "description": "Z 轴位置 (mm)"},
            "rot_x": {"type": "float", "default": 0, "description": "绕 X 轴旋转角度 (度)"},
            "rot_y": {"type": "float", "default": 0, "description": "绕 Y 轴旋转角度 (度)"},
            "rot_z": {"type": "float", "default": 0, "description": "绕 Z 轴旋转角度 (度)"},
        },
        "required": ["target"],
    },
    "move": {
        "description": "相对移动对象",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "dx": {"type": "float", "default": 0, "description": "X 方向位移 (mm)"},
            "dy": {"type": "float", "default": 0, "description": "Y 方向位移 (mm)"},
            "dz": {"type": "float", "default": 0, "description": "Z 方向位移 (mm)"},
        },
        "required": ["target"],
    },
    "rotate": {
        "description": "绕轴旋转对象",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "axis": {"type": "string", "default": "Z", "description": "旋转轴: X/Y/Z"},
            "angle": {"type": "float", "description": "旋转角度 (度)"},
            "origin_x": {"type": "float", "default": 0},
            "origin_y": {"type": "float", "default": 0},
            "origin_z": {"type": "float", "default": 0},
        },
        "required": ["target", "angle"],
    },
    "scale": {
        "description": "缩放对象（生成新的 Part::Feature）",
        "parameters": {
            "target": {"type": "string", "description": "源对象名称"},
            "scale_x": {"type": "float", "default": 1},
            "scale_y": {"type": "float", "default": 1},
            "scale_z": {"type": "float", "default": 1},
            "result_name": {"type": "string", "description": "结果对象名称（可选）"},
        },
        "required": ["target"],
    },
    "copy_object": {
        "description": "复制对象（仅 target+name；结果对象名=name，可供后续 rotate/fuse 引用）",
        "parameters": {
            "target": {"type": "string", "description": "源对象名称"},
            "name": {"type": "string", "description": "副本名称"},
        },
        "required": ["target", "name"],
    },
    "polar_pattern": {
        "description": (
            "圆周阵列：绕原点/指定中心旋转复制。"
            "count=总实例数（含原件）；间隔角=angle/count。"
            "副本命名 name_prefix2..name_prefix{count}（prefix 空则用 target_2..）。"
            "齿轮/法兰孔优先用本工具，禁止手写十几次 copy+rotate。"
        ),
        "parameters": {
            "target": {"type": "string", "description": "源对象（第1个实例，位于0°）"},
            "count": {"type": "int", "description": "总数量，含原件，>=2"},
            "angle": {"type": "float", "default": 360, "description": "阵列总角度（度），满圈360"},
            "axis": {"type": "string", "default": "Z", "description": "旋转轴 X/Y/Z"},
            "origin_x": {"type": "float", "default": 0, "description": "旋转中心 X"},
            "origin_y": {"type": "float", "default": 0, "description": "旋转中心 Y"},
            "origin_z": {"type": "float", "default": 0, "description": "旋转中心 Z"},
            "name_prefix": {
                "type": "string",
                "default": "",
                "description": "副本名前缀，如 Tooth → Tooth2..ToothN",
            },
            "fuse": {
                "type": "bool",
                "default": False,
                "description": "是否将原件+副本布尔并成一体",
            },
            "fuse_name": {
                "type": "string",
                "description": "fuse=true 时的结果对象名",
            },
        },
        "required": ["target", "count"],
    },
    "linear_pattern": {
        "description": (
            "线性阵列：沿 (dx,dy,dz) 间距复制。"
            "count=总实例数（含原件）。多孔/肋板/键槽重复优先用本工具。"
        ),
        "parameters": {
            "target": {"type": "string", "description": "源对象（第1个实例）"},
            "count": {"type": "int", "description": "总数量，含原件，>=2"},
            "dx": {"type": "float", "default": 10, "description": "相邻实例 X 间距 (mm)"},
            "dy": {"type": "float", "default": 0, "description": "相邻实例 Y 间距 (mm)"},
            "dz": {"type": "float", "default": 0, "description": "相邻实例 Z 间距 (mm)"},
            "name_prefix": {
                "type": "string",
                "default": "",
                "description": "副本名前缀，如 Hole → Hole2..HoleN",
            },
            "fuse": {
                "type": "bool",
                "default": False,
                "description": "是否将原件+副本布尔并成一体",
            },
            "fuse_name": {
                "type": "string",
                "description": "fuse=true 时的结果对象名",
            },
        },
        "required": ["target", "count"],
    },
    "align_objects": {
        "description": (
            "相对对齐：按世界 bbox 把 target 对齐到 reference（优先于 set_placement/move，避免猜绝对坐标）。"
            "mode=stack 表示 target.min 贴 reference.max（堆叠/并排）"
        ),
        "parameters": {
            "target": {"type": "string", "description": "要移动的对象"},
            "reference": {"type": "string", "description": "对齐参考对象"},
            "axis": {"type": "string", "default": "z", "description": "对齐轴: x/y/z"},
            "mode": {
                "type": "string",
                "default": "stack",
                "description": "min/max/center/stack",
            },
            "offset": {"type": "float", "default": 0, "description": "额外间隙 (mm)"},
        },
        "required": ["target", "reference"],
    },
    "place_relative": {
        "description": (
            "相对放置：把 target 的 bbox 中心放到 reference 的锚点 + (dx,dy,dz)。"
            "优先于手算绝对坐标再 set_placement"
        ),
        "parameters": {
            "target": {"type": "string", "description": "要移动的对象"},
            "reference": {"type": "string", "description": "参考对象"},
            "anchor": {
                "type": "string",
                "default": "center",
                "description": "center/top/bottom/left/right/front/back",
            },
            "dx": {"type": "float", "default": 0},
            "dy": {"type": "float", "default": 0},
            "dz": {"type": "float", "default": 0},
        },
        "required": ["target", "reference"],
    },
    "distribute_along": {
        "description": "沿轴等间距排列多个对象（首个不动）",
        "parameters": {
            "targets": {
                "type": "string",
                "description": "逗号分隔的对象名，如 Wheel1,Wheel2,Wheel3,Wheel4",
            },
            "axis": {"type": "string", "default": "x", "description": "x/y/z"},
            "spacing": {"type": "float", "description": "相邻对象间隙 (mm)"},
        },
        "required": ["targets", "spacing"],
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
    # ── export ──
    "save_fcstd": {
        "description": "保存 FreeCAD 文档",
        "parameters": {
            "filepath": {"type": "string", "description": "保存路径"},
        },
        "required": ["filepath"],
    },
    "export_step": {
        "description": "导出对象为 STEP 文件",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "filepath": {"type": "string", "description": "导出路径 (.step/.stp)"},
        },
        "required": ["target", "filepath"],
    },
    "export_stl": {
        "description": "导出对象为 STL 网格文件",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "filepath": {"type": "string", "description": "导出路径 (.stl)"},
            "tolerance": {"type": "float", "default": 0.1, "description": "网格精度；仅在 tessellate 回退路径生效，原生 exportStl 忽略"},
        },
        "required": ["target", "filepath"],
    },
    # ── query (几何事实查询) ──
    "summarize_document": {
        "description": "查询当前文档的紧凑对象树、可见性和 bbox 摘要。空间操作前用于了解整体状态",
        "parameters": {},
        "required": [],
    },
    "get_object_detail": {
        "description": "查询单个对象的 placement、world bbox、size、center、topology、properties、visibility",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
        },
        "required": ["target"],
    },
    "measure_gap": {
        "description": "按 world bbox 测量两个对象在指定轴上的间隙/重叠，用于贴附校验和 repair",
        "parameters": {
            "obj_a": {"type": "string", "description": "对象 A 名称"},
            "obj_b": {"type": "string", "description": "对象 B 名称"},
            "axis": {"type": "string", "default": "X", "description": "测量轴: X/Y/Z"},
            "tolerance": {"type": "float", "default": 0.5, "description": "认为贴附的最大 gap (mm)"},
        },
        "required": ["obj_a", "obj_b", "axis"],
    },
    "compare_orientation": {
        "description": "基于 bbox 判断对象朝向。圆柱用最薄轴作为实际轴，普通对象用最长轴；各向尺寸接近时视为各向同性并判定通过",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
            "expected_axis": {"type": "string", "default": "Z", "description": "期望轴: X/Y/Z"},
            "tolerance_ratio": {"type": "float", "default": 0.2, "description": "最长轴与最短轴尺寸差比例小于该值时视为各向同性（无法可靠判断朝向）"},
        },
        "required": ["target", "expected_axis"],
    },
    "list_topology": {
        "description": "列出对象所有面/边的编号、中心、法向、长度。倒角/选面拉伸前必须先调用",
        "parameters": {
            "target": {"type": "string", "description": "目标对象名称"},
        },
        "required": ["target"],
    },
    # ── sketch (草图) ──
    "create_body": {
        "description": "创建 PartDesign Body 容器",
        "parameters": {
            "name": {"type": "string", "description": "Body 名称"},
        },
        "required": ["name"],
    },
    "create_sketch": {
        "description": "在基准面 XY/XZ/YZ 上创建草图",
        "parameters": {
            "name": {"type": "string", "description": "草图名称"},
            "plane": {"type": "string", "default": "XY", "description": "XY, XZ, YZ"},
            "body": {"type": "string", "description": "所属 Body 名称（可选）"},
            "pos_x": {"type": "float", "default": 0},
            "pos_y": {"type": "float", "default": 0},
            "pos_z": {"type": "float", "default": 0},
            "map_mode": {"type": "string", "default": "FlatFace", "description": "兼容保留参数，基准面草图中不生效"},
        },
        "required": ["name"],
    },
    "create_sketch_on_face": {
        "description": "在已有实体的面上创建草图（选面再拉伸的第一步）",
        "parameters": {
            "name": {"type": "string", "description": "草图名称"},
            "target": {"type": "string", "description": "面所在的实体对象名"},
            "face": {"type": "string", "default": "Face1", "description": "面编号 Face1..FaceN，先用 list_topology 确认"},
            "body": {"type": "string", "description": "所属 Body（可选）"},
            "map_mode": {"type": "string", "default": "FlatFace"},
        },
        "required": ["name", "target", "face"],
    },
    "sketch_add_line": {
        "description": "在草图中添加线段",
        "parameters": {
            "sketch": {"type": "string", "description": "草图对象名"},
            "x1": {"type": "float", "default": 0}, "y1": {"type": "float", "default": 0},
            "x2": {"type": "float", "default": 10}, "y2": {"type": "float", "default": 0},
        },
        "required": ["sketch"],
    },
    "sketch_add_rect": {
        "description": "在草图中添加矩形（4条线段）",
        "parameters": {
            "sketch": {"type": "string", "description": "草图对象名"},
            "x": {"type": "float", "default": 0}, "y": {"type": "float", "default": 0},
            "width": {"type": "float", "default": 10}, "height": {"type": "float", "default": 10},
        },
        "required": ["sketch", "width", "height"],
    },
    "sketch_add_circle": {
        "description": "在草图中添加圆",
        "parameters": {
            "sketch": {"type": "string", "description": "草图对象名"},
            "center_x": {"type": "float", "default": 0}, "center_y": {"type": "float", "default": 0},
            "radius": {"type": "float", "description": "半径 (mm)"},
        },
        "required": ["sketch", "radius"],
    },
    "sketch_add_arc": {
        "description": "在草图中添加圆弧。FreeCAD API: Part.ArcOfCircle。mode=three_point 用起点/中点/终点；mode=center 用圆心+半径+起止角(度)",
        "parameters": {
            "sketch": {"type": "string", "description": "草图对象名"},
            "mode": {"type": "string", "default": "three_point", "description": "three_point | center"},
            "x1": {"type": "float", "default": 0, "description": "三点模式：起点 X"},
            "y1": {"type": "float", "default": 0, "description": "三点模式：起点 Y"},
            "x2": {"type": "float", "default": 5, "description": "三点模式：弧上中点 X"},
            "y2": {"type": "float", "default": 5, "description": "三点模式：弧上中点 Y"},
            "x3": {"type": "float", "default": 10, "description": "三点模式：终点 X"},
            "y3": {"type": "float", "default": 0, "description": "三点模式：终点 Y"},
            "center_x": {"type": "float", "default": 0, "description": "center 模式：圆心 X"},
            "center_y": {"type": "float", "default": 0, "description": "center 模式：圆心 Y"},
            "radius": {"type": "float", "default": 10, "description": "center 模式：半径 (mm)"},
            "start_angle": {"type": "float", "default": 0, "description": "center 模式：起始角 (度)"},
            "end_angle": {"type": "float", "default": 180, "description": "center 模式：终止角 (度)"},
        },
        "required": ["sketch"],
    },
    "sketch_add_polyline": {
        "description": "在草图中添加折线（连续 LineSegment + Coincident，对应 Sketcher Create Polyline）",
        "parameters": {
            "sketch": {"type": "string", "description": "草图对象名"},
            "points": {
                "type": "list",
                "description": "点列 [[x,y], ...] 或 [{\"x\":..,\"y\":..}, ...]，至少 2 点",
            },
            "closed": {"type": "bool", "default": False, "description": "是否闭合（首尾相连）"},
        },
        "required": ["sketch", "points"],
    },
    "sketch_add_bspline": {
        "description": "在草图中添加 B 样条。FreeCAD API: Part.BSplineCurve.interpolate / buildFromPoles + sketch.addGeometry",
        "parameters": {
            "sketch": {"type": "string", "description": "草图对象名"},
            "points": {
                "type": "list",
                "description": "点列 [[x,y], ...]。interpolate 模式为过点；poles 模式为控制点",
            },
            "mode": {
                "type": "string",
                "default": "interpolate",
                "description": "interpolate=曲线过点（推荐画轮廓）；poles=控制点",
            },
            "degree": {"type": "int", "default": 3, "description": "样条次数，通常 3"},
            "periodic": {"type": "bool", "default": False, "description": "是否周期/闭合样条"},
        },
        "required": ["sketch", "points"],
    },
    "sketch_add_constraint": {
        "description": "添加草图约束（Coincident/Horizontal/Vertical/Radius等）",
        "parameters": {
            "sketch": {"type": "string", "description": "草图对象名"},
            "constraint_type": {"type": "string", "default": "Coincident"},
            "geo1": {"type": "int", "default": 0, "description": "第一几何索引 (0-based)"},
            "point1": {"type": "int", "default": 1, "description": "第一几何端点 (1=起点, 2=终点)"},
            "geo2": {"type": "int", "description": "第二几何索引，0-based（可选）"},
            "point2": {"type": "int", "default": 1, "description": "第二几何端点 (1=起点, 2=终点)"},
        },
        "required": ["sketch", "constraint_type"],
    },
    # ── partdesign (特征链) ──
    "pad_sketch": {
        "description": "拉伸草图 (PartDesign::Pad)",
        "parameters": {
            "name": {"type": "string", "description": "Pad 名称"},
            "sketch": {"type": "string", "description": "草图对象名"},
            "length": {"type": "float", "description": "拉伸长度 (mm)"},
            "body": {"type": "string", "description": "Body 名称（可选）"},
            "reversed": {"type": "bool", "default": False},
            "midplane": {"type": "bool", "default": False},
            "type": {"type": "string", "default": "Length", "description": "Length|TwoLengths|UpToLast|UpToFirst"},
        },
        "required": ["name", "sketch", "length"],
    },
    "pocket_sketch": {
        "description": "切除拉伸 (PartDesign::Pocket)",
        "parameters": {
            "name": {"type": "string", "description": "Pocket 名称"},
            "sketch": {"type": "string", "description": "草图对象名"},
            "length": {"type": "float", "description": "切除深度 (mm)"},
            "body": {"type": "string", "description": "Body 名称（可选）"},
            "reversed": {"type": "bool", "default": False},
            "type": {"type": "string", "default": "Length"},
        },
        "required": ["name", "sketch", "length"],
    },
    "pad_to_face": {
        "description": "拉伸草图到指定面 (UpToFace)；target 须与 Pad 同属一个 Body，否则回退 Length",
        "parameters": {
            "name": {"type": "string", "description": "Pad 名称"},
            "sketch": {"type": "string", "description": "草图对象名"},
            "target": {"type": "string", "description": "终止面所在实体（须同 Body）"},
            "face": {"type": "string", "default": "Face1", "description": "终止面编号"},
            "length": {"type": "float", "default": 10, "description": "target 不在同 Body 时的回退长度"},
            "body": {"type": "string", "description": "Body 名称（可选）"},
            "offset": {"type": "float", "default": 0, "description": "距终止面偏移"},
        },
        "required": ["name", "sketch", "target", "face"],
    },
    "revolve_sketch": {
        "description": "旋转草图 (PartDesign::Revolution)，绕草图 H_Axis/V_Axis（由 axis_x/y/z 近似选择）",
        "parameters": {
            "name": {"type": "string", "description": "特征名称"},
            "sketch": {"type": "string", "description": "草图对象名"},
            "axis_x": {"type": "float", "default": 0}, "axis_y": {"type": "float", "default": 0},
            "axis_z": {"type": "float", "default": 1, "description": "旋转轴向量，默认 Z"},
            "angle": {"type": "float", "default": 360, "description": "旋转角度"},
            "body": {"type": "string", "description": "Body 名称（可选）"},
        },
        "required": ["name", "sketch"],
    },
    "extrude_sketch": {
        "description": "Part 模式拉伸草图（无需 Body，生成 Part::Feature）",
        "parameters": {
            "name": {"type": "string", "description": "结果对象名"},
            "sketch": {"type": "string", "description": "草图对象名"},
            "length": {"type": "float", "description": "拉伸长度 (mm)"},
            "direction_x": {"type": "float", "default": 0},
            "direction_y": {"type": "float", "default": 0},
            "direction_z": {"type": "float", "default": 1},
        },
        "required": ["name", "sketch", "length"],
    },
    # ── surface (曲面) ──
    "make_loft": {
        "description": "放样：通过多个截面轮廓生成实体",
        "parameters": {
            "name": {"type": "string", "description": "结果对象名"},
            "profiles": {"type": "list", "description": "截面对象名列表（草图或线框，从下到上）"},
            "solid": {"type": "bool", "default": True, "description": "是否生成实体"},
            "ruled": {"type": "bool", "default": False, "description": "直纹面"},
        },
        "required": ["name", "profiles"],
    },
    "make_sweep": {
        "description": "扫掠：截面沿路径扫掠",
        "parameters": {
            "name": {"type": "string", "description": "结果对象名"},
            "profile": {"type": "string", "description": "截面轮廓对象名"},
            "path": {"type": "string", "description": "路径对象名（Wire/Sketch）"},
            "make_solid": {"type": "bool", "default": True},
            "frenet": {"type": "bool", "default": False},
        },
        "required": ["name", "profile", "path"],
    },
    "make_revolve": {
        "description": "旋转体：轮廓绕轴旋转（Part 模式）",
        "parameters": {
            "name": {"type": "string", "description": "结果对象名"},
            "profile": {"type": "string", "description": "轮廓对象名"},
            "axis_x": {"type": "float", "default": 0}, "axis_y": {"type": "float", "default": 0},
            "axis_z": {"type": "float", "default": 1},
            "origin_x": {"type": "float", "default": 0}, "origin_y": {"type": "float", "default": 0},
            "origin_z": {"type": "float", "default": 0},
            "angle": {"type": "float", "default": 360},
        },
        "required": ["name", "profile"],
    },
    # ── assembly (装配) ──
    "create_assembly": {
        "description": "创建装配容器",
        "parameters": {
            "name": {"type": "string", "description": "装配体名称"},
        },
        "required": ["name"],
    },
    "add_to_assembly": {
        "description": "将零件加入装配",
        "parameters": {
            "assembly": {"type": "string", "description": "装配体名称"},
            "part": {"type": "string", "description": "零件对象名"},
            "name": {"type": "string", "description": "Link 名称（可选）"},
        },
        "required": ["assembly", "part"],
    },
    "mate_planes": {
        "description": "平面对齐配合（基于 Placement 的 portable 实现）",
        "parameters": {
            "assembly": {"type": "string", "description": "装配体名称"},
            "part1": {"type": "string", "description": "零件1"},
            "part2": {"type": "string", "description": "零件2（被移动）"},
            "plane1": {"type": "string", "default": "+Z", "description": "零件1的面对: +Z/-Z/+X/-X/+Y/-Y"},
            "plane2": {"type": "string", "default": "-Z", "description": "零件2的面对"},
            "offset_x": {"type": "float", "default": 0},
            "offset_y": {"type": "float", "default": 0},
            "offset_z": {"type": "float", "default": 0},
        },
        "required": ["assembly", "part1", "part2"],
    },
    "mate_coaxial": {
        "description": "同轴配合（对齐中心）",
        "parameters": {
            "assembly": {"type": "string", "description": "装配体名称"},
            "part1": {"type": "string", "description": "零件1"},
            "part2": {"type": "string", "description": "零件2（被移动）"},
            "axis": {"type": "string", "default": "Z", "description": "同轴方向 X/Y/Z"},
            "offset_x": {"type": "float", "default": 0},
            "offset_y": {"type": "float", "default": 0},
            "offset_z": {"type": "float", "default": 0},
        },
        "required": ["assembly", "part1", "part2"],
    },
}


def get_tool_spec(tool_name: str) -> dict | None:
    return TOOL_SPECS.get(tool_name)


def list_tool_names() -> list[str]:
    return list(TOOL_SPECS.keys())
