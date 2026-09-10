# primitive_tools.py — Basic Part primitives (Box, Cylinder, Sphere, Cone, Torus)

import Part

from AICADAgent.cad_tools._helpers import apply_placement

_SUPPORTED_UNITS = {"mm", ""}


def _check_unit(unit: str) -> None:
    if unit not in _SUPPORTED_UNITS:
        raise ValueError(f"Unsupported unit '{unit}': only mm is supported")


def create_box(doc, name="Box", length=10, width=10, height=10, unit="mm",
               pos_x=0, pos_y=0, pos_z=0, anchor="min"):
    """Create a Part::Box.

    anchor:
      - "min" (default): pos = bbox corner (xmin,ymin,zmin) — FreeCAD native
      - "center": pos = bbox center (internally converted to corner placement)
    """
    _check_unit(unit)
    if float(length) <= 0 or float(width) <= 0 or float(height) <= 0:
        raise ValueError(f"Box dimensions must be positive, got {length}x{width}x{height}")
    mode = str(anchor or "min").strip().lower()
    if mode not in {"min", "corner", "center"}:
        raise ValueError(f"anchor must be 'min' or 'center', got {anchor!r}")
    px, py, pz = float(pos_x), float(pos_y), float(pos_z)
    if mode == "center":
        px -= float(length) / 2.0
        py -= float(width) / 2.0
        pz -= float(height) / 2.0
    box = doc.addObject("Part::Box", name)
    box.Length = length
    box.Width = width
    box.Height = height
    box.Label = name
    apply_placement(box, px, py, pz)
    return {
        "tool": "create_box",
        "object": box.Name,
        "label": box.Label,
        "type": "Part::Box",
        "anchor": "center" if mode == "center" else "min",
    }


def create_cylinder(doc, name="Cylinder", radius=10, height=20, unit="mm",
                    pos_x=0, pos_y=0, pos_z=0, rot_x=0, rot_y=0, rot_z=0):
    """Create a Part::Cylinder in the given document with optional position/rotation."""
    _check_unit(unit)
    if float(radius) <= 0 or float(height) <= 0:
        raise ValueError(f"Cylinder radius/height must be positive, got r={radius} h={height}")
    cyl = doc.addObject("Part::Cylinder", name)
    cyl.Radius = radius
    cyl.Height = height
    cyl.Label = name
    apply_placement(cyl, pos_x, pos_y, pos_z, rot_x, rot_y, rot_z)
    return {"tool": "create_cylinder", "object": cyl.Name, "label": cyl.Label, "type": "Part::Cylinder"}


def create_sphere(doc, name="Sphere", radius=10, unit="mm", pos_x=0, pos_y=0, pos_z=0):
    """Create a Part::Sphere. Reference point is sphere center."""
    _check_unit(unit)
    if float(radius) <= 0:
        raise ValueError(f"Sphere radius must be positive, got {radius}")
    sphere = doc.addObject("Part::Sphere", name)
    sphere.Radius = radius
    sphere.Label = name
    apply_placement(sphere, pos_x, pos_y, pos_z)
    return {"tool": "create_sphere", "object": sphere.Name, "label": sphere.Label, "type": "Part::Sphere"}


def create_cone(doc, name="Cone", radius1=10, radius2=0, height=20, unit="mm",
                pos_x=0, pos_y=0, pos_z=0, rot_x=0, rot_y=0, rot_z=0):
    """Create a Part::Cone. Axis along local +Z; pos = bottom-face center."""
    _check_unit(unit)
    if float(radius1) < 0 or float(radius2) < 0 or float(radius1) + float(radius2) <= 0:
        raise ValueError(f"Cone radii must be non-negative and sum > 0, got r1={radius1} r2={radius2}")
    if float(height) <= 0:
        raise ValueError(f"Cone height must be positive, got {height}")
    cone = doc.addObject("Part::Cone", name)
    cone.Radius1 = radius1
    cone.Radius2 = radius2
    cone.Height = height
    cone.Label = name
    apply_placement(cone, pos_x, pos_y, pos_z, rot_x, rot_y, rot_z)
    return {"tool": "create_cone", "object": cone.Name, "label": cone.Label, "type": "Part::Cone"}


def create_torus(doc, name="Torus", radius1=20, radius2=5, unit="mm",
                 pos_x=0, pos_y=0, pos_z=0, rot_x=0, rot_y=0, rot_z=0):
    """Create a Part::Torus. Major ring in local XY (axis +Z); pos = torus center."""
    _check_unit(unit)
    if float(radius1) <= 0 or float(radius2) <= 0:
        raise ValueError(f"Torus radii must be positive, got R={radius1} r={radius2}")
    if float(radius2) >= float(radius1):
        raise ValueError(f"Torus minor radius must be < major radius, got R={radius1} r={radius2}")
    torus = doc.addObject("Part::Torus", name)
    torus.Radius1 = radius1
    torus.Radius2 = radius2
    torus.Label = name
    apply_placement(torus, pos_x, pos_y, pos_z, rot_x, rot_y, rot_z)
    return {"tool": "create_torus", "object": torus.Name, "label": torus.Label, "type": "Part::Torus"}


def create_wedge(
    doc,
    name="Wedge",
    length=40,
    width=20,
    height=10,
    tip_scale=0.4,
    taper_axis="Y",
    unit="mm",
    pos_x=0,
    pos_y=0,
    pos_z=0,
    rot_x=0,
    rot_y=0,
    rot_z=0,
    anchor="center",
):
    """[TEST] 楔形/锥台块：沿 taper_axis 从全尺寸收到 tip_scale。

    length/width/height → X/Y/Z。tip_scale∈(0,1] 为远端相对近端比例。
    """
    import FreeCAD
    import Part

    _check_unit(unit)
    L, W, H = float(length), float(width), float(height)
    ts = float(tip_scale)
    if L <= 0 or W <= 0 or H <= 0:
        raise ValueError(f"wedge dimensions must be positive, got {L}x{W}x{H}")
    if ts <= 0 or ts > 1:
        raise ValueError(f"tip_scale must be in (0,1], got {tip_scale}")
    axis = str(taper_axis or "Y").strip().upper()[:1]
    if axis not in {"X", "Y", "Z"}:
        raise ValueError(f"taper_axis must be X/Y/Z, got {taper_axis!r}")

    def _face_yz(y, sx, sz):
        hx, hz = sx / 2.0, sz / 2.0
        pts = [
            FreeCAD.Vector(-hx, y, -hz),
            FreeCAD.Vector(hx, y, -hz),
            FreeCAD.Vector(hx, y, hz),
            FreeCAD.Vector(-hx, y, hz),
        ]
        return Part.Face(Part.makePolygon(pts + [pts[0]]))

    def _face_xz(x, sy, sz):
        hy, hz = sy / 2.0, sz / 2.0
        pts = [
            FreeCAD.Vector(x, -hy, -hz),
            FreeCAD.Vector(x, hy, -hz),
            FreeCAD.Vector(x, hy, hz),
            FreeCAD.Vector(x, -hy, hz),
        ]
        return Part.Face(Part.makePolygon(pts + [pts[0]]))

    def _face_xy(z, sx, sy):
        hx, hy = sx / 2.0, sy / 2.0
        pts = [
            FreeCAD.Vector(-hx, -hy, z),
            FreeCAD.Vector(hx, -hy, z),
            FreeCAD.Vector(hx, hy, z),
            FreeCAD.Vector(-hx, hy, z),
        ]
        return Part.Face(Part.makePolygon(pts + [pts[0]]))

    # 局部：近端 -extent/2 全尺寸，远端 +extent/2 收 tip_scale，几何中心在原点
    if axis == "Y":
        y0, y1 = -W / 2.0, W / 2.0
        f1, f2 = _face_yz(y0, L, H), _face_yz(y1, L * ts, H * ts)
    elif axis == "X":
        x0, x1 = -L / 2.0, L / 2.0
        f1, f2 = _face_xz(x0, W, H), _face_xz(x1, W * ts, H * ts)
    else:
        z0, z1 = -H / 2.0, H / 2.0
        f1, f2 = _face_xy(z0, L, W), _face_xy(z1, L * ts, W * ts)

    solid = Part.makeLoft([f1, f2], True)
    mode = str(anchor or "center").strip().lower()
    if mode not in {"center", "min", "corner"}:
        raise ValueError(f"anchor must be 'min' or 'center', got {anchor!r}")
    if mode != "center":
        bb = solid.BoundBox
        solid.translate(FreeCAD.Vector(-bb.XMin, -bb.YMin, -bb.ZMin))
        px, py, pz = float(pos_x), float(pos_y), float(pos_z)
    else:
        px, py, pz = float(pos_x), float(pos_y), float(pos_z)

    feat = doc.addObject("Part::Feature", name)
    feat.Label = name
    feat.Shape = solid
    apply_placement(feat, px, py, pz, rot_x, rot_y, rot_z)
    return {
        "tool": "create_wedge",
        "object": feat.Name,
        "label": feat.Label,
        "type": "Part::Feature",
        "status": "test",
        "taper_axis": axis,
        "tip_scale": ts,
    }
