# surface_tools.py — Loft, sweep, revolve (Part module)
# API ref: Part.makeLoft, Wire.makePipeShell

import FreeCAD
import Part

from AICADAgent.cad_tools._helpers import get_object, get_shape


def _collect_profiles(doc, profile_names: list):
    try:
        doc.recompute()
    except Exception:
        pass
    profiles = []
    for name in profile_names:
        obj = get_object(doc, name)
        shape = get_shape(obj)
        if shape.Faces:
            profiles.append(shape.Faces[0])
        elif shape.Wires:
            profiles.append(Part.Face(shape.Wires[0]))
        elif shape.Edges:
            try:
                wire = Part.Wire(Part.__sortEdges__(list(shape.Edges)))
                profiles.append(Part.Face(wire) if wire.isClosed() else wire)
            except Exception:
                profiles.append(shape)
        else:
            profiles.append(shape)
    return profiles


def make_loft(doc, name="Loft", profiles=None, solid=True, ruled=False):
    """Loft through multiple profile objects (sketches or wires)."""
    profiles = profiles or []
    shapes = _collect_profiles(doc, profiles)
    result = Part.makeLoft(shapes, bool(solid), bool(ruled))
    feat = doc.addObject("Part::Feature", name)
    feat.Label = name
    feat.Shape = result
    return {"tool": "make_loft", "object": feat.Name, "profiles": profiles, "type": "Part::Feature"}


def make_sweep(doc, name="Sweep", profile="", path="", make_solid=True, frenet=False):
    """[TEST] Sweep profile along path wire.

    圆形截面：把路径插值为单根 BSpline 再 Part.makeTube（避免折线多段 fuse 丢段成 L）。
    其它截面：makePipeShell / makePipe。
    Code Mode: cad.sweep(name=..., profile=..., path=..., solid=True, frenet=False)
    """
    try:
        doc.recompute()
    except Exception:
        pass
    from AICADAgent.cad_tools._helpers import get_world_shape

    prof_obj = get_object(doc, profile)
    path_obj = get_object(doc, path)
    prof_shape = get_world_shape(prof_obj)
    path_shape = get_world_shape(path_obj)

    if prof_shape.Faces:
        section = prof_shape.Faces[0].OuterWire
    elif prof_shape.Wires:
        section = prof_shape.Wires[0]
    else:
        section = prof_shape

    if path_shape.Wires:
        wire = path_shape.Wires[0]
    elif path_shape.Edges:
        wire = Part.Wire(Part.__sortEdges__(list(path_shape.Edges)))
    else:
        raise ValueError(f"path '{path}' has no Wire/Edges to sweep along")

    radius = None
    try:
        edges = list(section.Edges) if hasattr(section, "Edges") else []
        if len(edges) == 1 and hasattr(edges[0].Curve, "Radius"):
            radius = float(edges[0].Curve.Radius)
    except Exception:
        radius = None

    result = None
    method = "pipeshell"
    if radius and radius > 0:
        # 折线 → 排序边 → 单根样条 makeTube（多段 fuse 易丢段成 L）
        ordered = Part.__sortEdges__(list(wire.Edges))
        pts = []
        for edge in ordered:
            n = max(2, int(edge.Length / 8.0) + 1)
            for i in range(n + 1):
                u = edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) * (i / float(n))
                p = edge.valueAt(u)
                if not pts or (p - pts[-1]).Length > 1e-4:
                    pts.append(p)
        if len(pts) < 2:
            raise ValueError(f"path '{path}' has too few sample points for tube")
        try:
            bspline = Part.BSplineCurve()
            bspline.interpolate(pts)
            result = Part.makeTube(bspline.toShape(), radius)
            method = "tube_bspline"
        except Exception:
            tubes = [Part.makeTube(e, radius) for e in ordered]
            result = tubes[0]
            for t in tubes[1:]:
                result = result.fuse(t)
            method = "tube_segments"
        try:
            if result.Shells and not result.Solids:
                result = Part.makeSolid(result.Shells[0])
        except Exception:
            pass
    else:
        try:
            result = wire.makePipeShell([section], bool(make_solid), bool(frenet))
            if result is None or result.isNull() or abs(float(result.Volume)) < 1e-6:
                result = None
        except Exception:
            result = None
        if result is None:
            result = wire.makePipe(section)

    if result is None or result.isNull():
        raise ValueError(f"sweep failed for profile='{profile}' path='{path}'")

    feat = doc.addObject("Part::Feature", name)
    feat.Label = name
    feat.Shape = result
    return {
        "tool": "make_sweep",
        "object": feat.Name,
        "profile": profile,
        "path": path,
        "type": "Part::Feature",
        "status": "test",
        "method": method,
    }


def make_revolve(doc, name="Revolve", profile="", axis_x=0, axis_y=0, axis_z=1,
                 origin_x=0, origin_y=0, origin_z=0, angle=360):
    """Revolve profile around axis (Part workbench)."""
    prof_shape = get_shape(get_object(doc, profile))
    base = prof_shape.Faces[0] if prof_shape.Faces else Part.Face(prof_shape.Wires[0])
    axis = FreeCAD.Vector(float(axis_x), float(axis_y), float(axis_z))
    if axis.Length == 0:
        axis = FreeCAD.Vector(0, 0, 1)
    origin = FreeCAD.Vector(float(origin_x), float(origin_y), float(origin_z))
    result = base.revolve(origin, axis, float(angle))
    feat = doc.addObject("Part::Feature", name)
    feat.Label = name
    feat.Shape = result
    return {"tool": "make_revolve", "object": feat.Name, "profile": profile, "type": "Part::Feature"}
