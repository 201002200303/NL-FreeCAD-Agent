# feature_tools.py — Feature operations: fillet, chamfer, cut_hole, mirror
# API ref: TopoShape.makeFillet / makeChamfer / mirror; Part::Cut for holes

import FreeCAD
import Part

from AICADAgent.cad_tools._helpers import (
    get_object,
    get_shape,
    assign_shape_result,
    select_edges,
)


def add_fillet(doc, target="", radius=1, edge_selector="all", face_selector=None, result_name=None):
    if float(radius) <= 0:
        raise ValueError(f"Fillet radius must be positive, got {radius}")
    obj = get_object(doc, target)
    shape = get_shape(obj)
    edges = select_edges(shape, edge_selector, face_selector)
    if not edges:
        raise ValueError(f"No edges matched selector '{edge_selector}'")
    new_shape = shape.makeFillet(float(radius), edges)
    feat = assign_shape_result(doc, target, new_shape, result_name or f"{target}_Fillet")
    return {
        "tool": "add_fillet",
        "object": feat.Name,
        "source": target,
        "radius": radius,
        "type": feat.TypeId,
    }


def add_chamfer(doc, target="", size=1, edge_selector="all", face_selector=None, result_name=None):
    if float(size) <= 0:
        raise ValueError(f"Chamfer size must be positive, got {size}")
    obj = get_object(doc, target)
    shape = get_shape(obj)
    edges = select_edges(shape, edge_selector, face_selector)
    if not edges:
        raise ValueError(f"No edges matched selector '{edge_selector}'")
    new_shape = shape.makeChamfer(float(size), edges)
    feat = assign_shape_result(doc, target, new_shape, result_name or f"{target}_Chamfer")
    return {
        "tool": "add_chamfer",
        "object": feat.Name,
        "source": target,
        "size": size,
        "type": feat.TypeId,
    }


def _axis_extent(bb, axis: str) -> float:
    axis = axis.upper()
    if axis == "X":
        return float(bb.XMax - bb.XMin)
    if axis == "Y":
        return float(bb.YMax - bb.YMin)
    return float(bb.ZMax - bb.ZMin)


def _place_drill_tool(cutter, axis: str, cx: float, cy: float, cz: float, height: float, bb):
    """Part::Cylinder 默认轴沿局部 +Z；按钻孔方向放置，略伸出实体两端。"""
    overhang = height * 0.25
    axis = axis.upper()
    if axis == "X":
        # 局部 Z → 世界 +X
        cutter.Placement = FreeCAD.Placement(
            FreeCAD.Vector(bb.XMin - overhang, cy, cz),
            FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 90),
        )
    elif axis == "Y":
        # 局部 Z → 世界 +Y
        cutter.Placement = FreeCAD.Placement(
            FreeCAD.Vector(cx, bb.YMin - overhang, cz),
            FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90),
        )
    else:
        cutter.Placement = FreeCAD.Placement(
            FreeCAD.Vector(cx, cy, bb.ZMin - overhang),
            FreeCAD.Rotation(),
        )


def _validate_cut_solid(shape, label: str):
    if shape is None or shape.isNull():
        raise ValueError(f"{label}: result shape is null")
    solids = getattr(shape, "Solids", None) or []
    if not solids:
        raise ValueError(f"{label}: result has no solids (cut removed the whole body?)")
    vol = float(getattr(shape, "Volume", 0) or 0)
    if vol <= 1e-6:
        raise ValueError(f"{label}: result volume ~0 (invalid cut)")


def _cut_hole_via_part_cut(
    doc,
    target_obj,
    *,
    hole_diameter: float,
    through_all: bool,
    pos_x,
    pos_y,
    pos_z,
    result_name: str,
    axis: str,
):
    """标准 Part 工作流：钻孔刀圆柱 + Part::Cut（布尔求差）。"""
    shape = get_shape(target_obj)
    bb = shape.BoundBox
    cx = bb.Center.x if pos_x is None else float(pos_x)
    cy = bb.Center.y if pos_y is None else float(pos_y)
    cz = bb.Center.z if pos_z is None else float(pos_z)
    axis = (axis or "Z").upper()
    if axis not in {"X", "Y", "Z"}:
        raise ValueError(f"axis must be X/Y/Z, got {axis!r}")

    extent = _axis_extent(bb, axis)
    if extent <= 0:
        raise ValueError(f"target '{target_obj.Name}' has zero extent along {axis}")
    height = extent * 1.5 if through_all else max(extent, float(hole_diameter))
    radius = float(hole_diameter) / 2.0

    tool_name = f"{result_name}_DrillTool"
    cut_name = result_name
    cutter = None
    cut = None
    try:
        cutter = doc.addObject("Part::Cylinder", tool_name)
        cutter.Label = tool_name
        cutter.Radius = radius
        cutter.Height = float(height)
        _place_drill_tool(cutter, axis, cx, cy, cz, float(height), bb)

        cut = doc.addObject("Part::Cut", cut_name)
        cut.Label = cut_name
        cut.Base = target_obj
        cut.Tool = cutter
        doc.recompute()

        _validate_cut_solid(cut.Shape, "cut_hole")

        # Part::Cut 树里保留 Base/Tool；视口只显示求差结果
        try:
            cutter.Visibility = False
            target_obj.Visibility = False
            cut.Visibility = True
        except Exception:
            pass

        return {
            "tool": "cut_hole",
            "object": cut.Name,
            "source": target_obj.Name,
            "drill_tool": cutter.Name,
            "hole_diameter": hole_diameter,
            "axis": axis,
            "method": "part_cut",
            "type": cut.TypeId,
            "message": (
                f"Part::Cut 布尔求差完成；后续请引用 '{cut.Name}'，"
                f"勿再改已隐藏的 '{target_obj.Name}'"
            ),
        }
    except Exception:
        # 失败时回滚新建对象，保持原件可见
        for obj in (cut, cutter):
            if obj is not None:
                try:
                    doc.removeObject(obj.Name)
                except Exception:
                    pass
        try:
            target_obj.Visibility = True
        except Exception:
            pass
        raise


def _cut_hole_via_pocket(
    doc,
    target_obj,
    *,
    body_name: str,
    hole_diameter: float,
    through_all: bool,
    pos_x,
    pos_y,
    result_name: str,
):
    """PartDesign 工作流：草图圆 + Pocket（ThroughAll / Length）。"""
    from AICADAgent.cad_tools.sketch_tools import (
        create_sketch,
        sketch_add_circle,
    )
    from AICADAgent.cad_tools.partdesign_tools import pocket_sketch

    body = get_object(doc, body_name)
    shape = get_shape(target_obj)
    bb = shape.BoundBox
    # 草图在 XY：孔轴沿 Body/草图法向（通常 +Z）
    cx = bb.Center.x if pos_x is None else float(pos_x)
    cy = bb.Center.y if pos_y is None else float(pos_y)
    radius = float(hole_diameter) / 2.0

    sk_name = f"{result_name}_HoleSketch"
    create_sketch(doc, name=sk_name, plane="XY", body=body_name, pos_z=float(bb.ZMax))
    sketch_add_circle(doc, sketch=sk_name, center_x=cx, center_y=cy, radius=radius)

    pocket_type = "ThroughAll" if through_all else "Length"
    length = float(bb.ZMax - bb.ZMin) * 1.2
    pocket_sketch(
        doc,
        name=result_name,
        sketch=sk_name,
        length=length,
        body=body_name,
        reversed=True,
        type=pocket_type,
    )
    doc.recompute()
    pocket = get_object(doc, result_name)
    _validate_cut_solid(get_shape(pocket), "cut_hole/pocket")

    return {
        "tool": "cut_hole",
        "object": pocket.Name,
        "source": target_obj.Name,
        "body": body.Name,
        "sketch": sk_name,
        "hole_diameter": hole_diameter,
        "axis": "Z",
        "method": "pocket_sketch",
        "type": pocket.TypeId,
        "message": (
            f"PartDesign Pocket 打孔完成（草图 {sk_name}）；"
            f"后续请引用 Body/特征 '{pocket.Name}'"
        ),
    }


def cut_hole(
    doc,
    target="",
    hole_diameter=5,
    through_all=True,
    pos_x=None,
    pos_y=None,
    pos_z=None,
    result_name=None,
    axis="Z",
    body=None,
):
    """在目标实体上打圆柱孔。

    优先建模逻辑（不再用「内存 cut + 藏原件糊成 Feature」）：
    1. 若提供 body：草图圆 + PartDesign::Pocket（ThroughAll）
    2. 否则：Part::Cylinder 钻孔刀 + Part::Cut 布尔求差

    成功后原基体在树中保留但隐藏（FreeCAD 布尔/特征树惯例）；
    失败则删除本次新建对象并恢复可见性。
    """
    if float(hole_diameter) <= 0:
        raise ValueError(f"Hole diameter must be positive, got {hole_diameter}")
    target_obj = get_object(doc, target)
    out_name = result_name or f"{target}_Hole"

    if body:
        return _cut_hole_via_pocket(
            doc,
            target_obj,
            body_name=body,
            hole_diameter=float(hole_diameter),
            through_all=bool(through_all),
            pos_x=pos_x,
            pos_y=pos_y,
            result_name=out_name,
        )

    return _cut_hole_via_part_cut(
        doc,
        target_obj,
        hole_diameter=float(hole_diameter),
        through_all=bool(through_all),
        pos_x=pos_x,
        pos_y=pos_y,
        pos_z=pos_z,
        result_name=out_name,
        axis=axis or "Z",
    )


def mirror(doc, target="", name="Mirror", plane="XY", origin_x=0, origin_y=0, origin_z=0):
    """[已下线] 勿再注册到 TOOL_REGISTRY。保留函数仅供本地旧测；chat 对称用对侧 create_*。"""
    raise RuntimeError(
        "mirror tool is disabled; create the opposite side with create_* "
        "(negate X about midline) or use linear_pattern/polar_pattern"
    )
