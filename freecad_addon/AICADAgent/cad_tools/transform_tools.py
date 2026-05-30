# transform_tools.py — Transform tools: move, rotate, scale, copy_object

import FreeCAD

from AICADAgent.cad_tools._helpers import get_object, get_shape


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
    """Rotate object around an axis (X/Y/Z) by angle in degrees."""
    obj = get_object(doc, target)
    axis_map = {
        "X": FreeCAD.Vector(1, 0, 0),
        "Y": FreeCAD.Vector(0, 1, 0),
        "Z": FreeCAD.Vector(0, 0, 1),
    }
    axis_vec = axis_map.get(axis.upper(), FreeCAD.Vector(0, 0, 1))
    origin = FreeCAD.Vector(float(origin_x), float(origin_y), float(origin_z))

    plm = obj.Placement
    plm.rotate(origin, axis_vec, float(angle))
    obj.Placement = plm
    return {
        "tool": "rotate",
        "object": target,
        "axis": axis.upper(),
        "angle": angle,
    }


def scale(doc, target="", scale_x=1, scale_y=1, scale_z=1, result_name=None):
    """Scale object shape uniformly or non-uniformly. Creates Part::Feature result."""
    obj = get_object(doc, target)
    shape = get_shape(obj)
    center = shape.BoundBox.Center
    scaled = shape.scale(float(scale_x), float(scale_y), float(scale_z), center)

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
        "scale": [scale_x, scale_y, scale_z],
        "type": "Part::Feature",
    }


def copy_object(doc, target="", name="Copy"):
    """Duplicate an object in the document."""
    src = get_object(doc, target)
    copy = doc.copyObject(src, False, name)
    copy.Label = name
    return {
        "tool": "copy_object",
        "object": copy.Name,
        "source": target,
        "type": copy.TypeId,
    }
