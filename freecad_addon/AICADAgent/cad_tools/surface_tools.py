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
    """Sweep profile along path wire (Part makePipeShell)."""
    prof_obj = get_object(doc, profile)
    path_obj = get_object(doc, path)
    prof_shape = get_shape(prof_obj)
    path_shape = get_shape(path_obj)

    if prof_shape.Faces:
        section = prof_shape.Faces[0].OuterWire
    elif prof_shape.Wires:
        section = prof_shape.Wires[0]
    else:
        section = prof_shape

    spine = path_shape.Wires[0] if path_shape.Wires else path_shape.Edges[0]
    if not hasattr(spine, "makePipeShell"):
        wire = Part.Wire([spine]) if not isinstance(spine, Part.Wire) else spine
    else:
        wire = spine if isinstance(spine, Part.Wire) else Part.Wire([spine])

    result = wire.makePipeShell([section], bool(make_solid), bool(frenet))
    feat = doc.addObject("Part::Feature", name)
    feat.Label = name
    feat.Shape = result
    return {"tool": "make_sweep", "object": feat.Name, "profile": profile, "path": path, "type": "Part::Feature"}


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
