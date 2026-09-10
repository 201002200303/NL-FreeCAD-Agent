# transform_tools.py — Transform tools: move, rotate, scale, copy_object

import FreeCAD

from AICADAgent.cad_tools._helpers import get_object, get_shape, get_world_shape, remove_objects
from AICADAgent.geometry_facts import exact_bbox


def move(doc, target="", dx=0, dy=0, dz=0):
    """Move object by relative offset."""
    obj = get_object(doc, target)
    plm = obj.Placement
    plm.Base = plm.Base + FreeCAD.Vector(float(dx), float(dy), float(dz))
    obj.Placement = plm
    return {
        "tool": "move",
        "object": target,
        "offset": [dx, dy, dz],
        "position": [plm.Base.x, plm.Base.y, plm.Base.z],
    }


def rotate(doc, target="", axis="Z", angle=0, origin_x=0, origin_y=0, origin_z=0):
    """绕给定中心旋转对象（公转 Base + 更新 Orientation）。

    FreeCAD Placement.rotate() 在部分版本只改朝向、不绕 pivot 移动 Base；
    这里显式做 R*(Base-pivot)+pivot，保证圆周布齿等场景正确。
    """
    obj = get_object(doc, target)
    axis_map = {
        "X": FreeCAD.Vector(1, 0, 0),
        "Y": FreeCAD.Vector(0, 1, 0),
        "Z": FreeCAD.Vector(0, 0, 1),
    }
    axis_vec = axis_map.get(str(axis).upper(), FreeCAD.Vector(0, 0, 1))
    pivot = FreeCAD.Vector(float(origin_x), float(origin_y), float(origin_z))
    rot = FreeCAD.Rotation(axis_vec, float(angle))

    plm = FreeCAD.Placement(obj.Placement)
    rel = plm.Base.sub(pivot)
    plm.Base = pivot.add(rot.multVec(rel))
    plm.Rotation = rot.multiply(plm.Rotation)
    obj.Placement = plm
    return {
        "tool": "rotate",
        "object": target,
        "axis": str(axis).upper(),
        "angle": angle,
        "origin": [float(origin_x), float(origin_y), float(origin_z)],
    }


def scale(doc, target="", scale_x=1, scale_y=1, scale_z=1, result_name=None):
    """Scale object shape uniformly or non-uniformly. Creates Part::Feature result.

    FreeCAD 1.1 Shape.scale(factor, [base]) is uniform-only; non-uniform uses Matrix.
    """
    sx, sy, sz = float(scale_x), float(scale_y), float(scale_z)
    if sx == 0 or sy == 0 or sz == 0:
        raise ValueError(f"Scale factors must be non-zero, got {scale_x}x{scale_y}x{scale_z}")
    obj = get_object(doc, target)
    # Must copy first: parametric Shape (Part::Sphere etc.) is immutable in FC 1.1+
    shape = get_shape(obj).copy()
    center = exact_bbox(shape).Center

    if abs(sx - sy) < 1e-12 and abs(sy - sz) < 1e-12:
        scaled = shape.scale(sx, center)
        if scaled is None:
            scaled = shape
    else:
        mat = FreeCAD.Matrix()
        mat.move(FreeCAD.Vector(-center.x, -center.y, -center.z))
        sm = FreeCAD.Matrix()
        sm.scale(sx, sy, sz)
        mat = sm.multiply(mat)
        mat.move(center)
        scaled = shape.transformGeometry(mat)

    out_name = result_name or f"{target}_Scaled"
    feat = doc.addObject("Part::Feature", out_name)
    feat.Label = out_name
    feat.Shape = scaled

    try:
        obj.Visibility = False
    except Exception:
        pass

    return {
        "tool": "scale",
        "object": feat.Name,
        "source": target,
        "scale": [sx, sy, sz],
        "type": "Part::Feature",
    }


def _unwrap_copy(copied):
    """FreeCAD copyObject may return an object or a sequence."""
    if isinstance(copied, (list, tuple)):
        if not copied:
            raise ValueError("copyObject returned an empty result")
        return copied[0]
    return copied


def _pattern_instance_name(name_prefix: str, target: str, index: int) -> str:
    prefix = (name_prefix or "").strip()
    if prefix:
        return f"{prefix}{index}"
    return f"{target}_{index}"


def copy_object(doc, target="", name="Copy"):
    """Duplicate an object; result Name/Label equal `name` for reliable lookup.

    FreeCAD Document.copyObject(obj, recursive=False, return_all=False) —
    the 3rd argument is a bool, NOT a name. We copy, then materialize a
    Part::Feature with the requested name so later tools can find it.
    """
    src = get_object(doc, target)
    out_name = str(name or "").strip()
    if not out_name:
        raise ValueError("copy_object requires a non-empty name")
    if doc.getObject(out_name) is not None:
        raise ValueError(f"Object already exists: {out_name}")

    tmp = _unwrap_copy(doc.copyObject(src, False))
    shape = get_shape(tmp).copy()
    placement = FreeCAD.Placement(tmp.Placement)
    tmp_name = tmp.Name
    try:
        doc.removeObject(tmp_name)
    except Exception:
        pass

    feat = doc.addObject("Part::Feature", out_name)
    feat.Label = out_name
    feat.Shape = shape
    feat.Placement = placement
    # Do NOT set "source": copy is not a replacement; executor name_map would
    # remap original → copy and break later modify_param / ops on the original.
    return {
        "tool": "copy_object",
        "object": feat.Name,
        "copied_from": target,
        "type": feat.TypeId,
    }


def polar_pattern(
    doc,
    target="",
    count=4,
    angle=360.0,
    axis="Z",
    origin_x=0.0,
    origin_y=0.0,
    origin_z=0.0,
    name_prefix="",
    fuse=False,
    fuse_name="",
):
    """Circular array around an axis.

    `count` = total instances including the original (at 0°).
    Creates count-1 copies at i * (angle/count) for i=1..count-1.
    Names: {name_prefix}2..{name_prefix}{count}, or {target}_2.. if prefix empty.
    If fuse=True, fuse original+copies into fuse_name.
    """
    src = get_object(doc, target)
    n = int(count)
    if n < 2:
        raise ValueError(f"polar_pattern count must be >= 2, got {count}")
    step = float(angle) / float(n)

    axis_map = {
        "X": FreeCAD.Vector(1, 0, 0),
        "Y": FreeCAD.Vector(0, 1, 0),
        "Z": FreeCAD.Vector(0, 0, 1),
    }
    axis_vec = axis_map.get(str(axis).upper(), FreeCAD.Vector(0, 0, 1))
    origin = FreeCAD.Vector(float(origin_x), float(origin_y), float(origin_z))

    created = []
    src_world = get_world_shape(src)
    for i in range(1, n):
        inst_name = _pattern_instance_name(name_prefix, target, i + 1)
        if doc.getObject(inst_name) is not None:
            raise ValueError(f"Object already exists: {inst_name}")
        # transformShape(增量矩阵)：在世界坐标 Shape 上绕 origin 旋转，
        # 几何与 Shape.Placement 同步，后续 fuse 按世界位姿正确布尔。
        rot = FreeCAD.Rotation(axis_vec, step * i)
        mat = FreeCAD.Matrix()
        mat.move(FreeCAD.Vector(-origin.x, -origin.y, -origin.z))
        mat = rot.toMatrix().multiply(mat)
        mat.move(origin)
        shape = src_world.copy().transformShape(mat)
        feat = doc.addObject("Part::Feature", inst_name)
        feat.Label = inst_name
        feat.Shape = shape
        # 不重置 feat.Placement：transformShape 后的 Shape 自带正确世界位姿，
        # 赋 identity 反而归零造成甩件。
        created.append(feat.Name)

    result = {
        "tool": "polar_pattern",
        "object": target,
        "created": created,
        "count": n,
        "angle": float(angle),
        "axis": str(axis).upper(),
        "step": step,
    }

    if fuse:
        fname = str(fuse_name or "").strip()
        if not fname:
            raise ValueError("polar_pattern fuse=True requires fuse_name")
        if doc.getObject(fname) is not None:
            raise ValueError(f"Object already exists: {fname}")
        members = [target] + created
        fused = get_world_shape(get_object(doc, members[0]))
        for m in members[1:]:
            fused = fused.fuse(get_world_shape(get_object(doc, m)))
        feat = doc.addObject("Part::Feature", fname)
        feat.Label = fname
        feat.Shape = fused
        # 根治幽灵件：fuse 后删源件，不要只 Visibility=False
        remove_objects(doc, members)
        result["object"] = feat.Name
        result["fused"] = feat.Name
        result["type"] = "Part::Feature"
        result["removed"] = list(members)

    return result


def linear_pattern(
    doc,
    target="",
    count=2,
    dx=10.0,
    dy=0.0,
    dz=0.0,
    name_prefix="",
    fuse=False,
    fuse_name="",
):
    """Linear array along a spacing vector (dx, dy, dz) between neighbors.

    `count` = total instances including the original.
    Creates count-1 copies at i*(dx,dy,dz) for i=1..count-1.
    """
    src = get_object(doc, target)
    n = int(count)
    if n < 2:
        raise ValueError(f"linear_pattern count must be >= 2, got {count}")

    created = []
    src_world = get_world_shape(src)
    for i in range(1, n):
        inst_name = _pattern_instance_name(name_prefix, target, i + 1)
        if doc.getObject(inst_name) is not None:
            raise ValueError(f"Object already exists: {inst_name}")
        # transformShape(增量矩阵)：在世界坐标 Shape 上平移。
        mat = FreeCAD.Matrix()
        mat.move(FreeCAD.Vector(float(dx) * i, float(dy) * i, float(dz) * i))
        shape = src_world.copy().transformShape(mat)
        feat = doc.addObject("Part::Feature", inst_name)
        feat.Label = inst_name
        feat.Shape = shape
        created.append(feat.Name)

    result = {
        "tool": "linear_pattern",
        "object": target,
        "created": created,
        "count": n,
        "spacing": [float(dx), float(dy), float(dz)],
    }

    if fuse:
        fname = str(fuse_name or "").strip()
        if not fname:
            raise ValueError("linear_pattern fuse=True requires fuse_name")
        if doc.getObject(fname) is not None:
            raise ValueError(f"Object already exists: {fname}")
        members = [target] + created
        fused = get_world_shape(get_object(doc, members[0]))
        for m in members[1:]:
            fused = fused.fuse(get_world_shape(get_object(doc, m)))
        feat = doc.addObject("Part::Feature", fname)
        feat.Label = fname
        feat.Shape = fused
        remove_objects(doc, members)
        result["object"] = feat.Name
        result["fused"] = feat.Name
        result["type"] = "Part::Feature"
        result["removed"] = list(members)

    return result
