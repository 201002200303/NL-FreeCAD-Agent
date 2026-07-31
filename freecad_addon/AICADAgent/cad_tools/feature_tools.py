# feature_tools.py — Feature operations: fillet, chamfer, cut_hole, mirror
# API ref: TopoShape.makeFillet / makeChamfer / mirror

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


def cut_hole(doc, target="", hole_diameter=5, through_all=True, pos_x=None, pos_y=None, pos_z=None,
             result_name=None):
    """Cut a cylindrical hole through target. Default position: shape center."""
    if float(hole_diameter) <= 0:
        raise ValueError(f"Hole diameter must be positive, got {hole_diameter}")
    obj = get_object(doc, target)
    shape = get_shape(obj)
    bb = shape.BoundBox
    cx = bb.Center.x if pos_x is None else float(pos_x)
    cy = bb.Center.y if pos_y is None else float(pos_y)
    cz = bb.Center.z if pos_z is None else float(pos_z)
    radius = float(hole_diameter) / 2.0
    height = (bb.ZMax - bb.ZMin) * 1.5 if through_all else (bb.ZMax - bb.ZMin)
    hole = Part.makeCylinder(
        radius, height,
        FreeCAD.Vector(cx, cy, bb.ZMin - height * 0.25),
        FreeCAD.Vector(0, 0, 1),
    )
    new_shape = shape.cut(hole)
    feat = assign_shape_result(doc, target, new_shape, result_name or f"{target}_Hole")
    return {
        "tool": "cut_hole",
        "object": feat.Name,
        "source": target,
        "hole_diameter": hole_diameter,
        "type": feat.TypeId,
    }


def mirror(doc, target="", name="Mirror", plane="XY", origin_x=0, origin_y=0, origin_z=0):
    """Mirror object across a plane (XY, XZ, YZ)."""
    obj = get_object(doc, target)
    shape = get_shape(obj)
    origin = FreeCAD.Vector(float(origin_x), float(origin_y), float(origin_z))
    normal_map = {
        "XY": FreeCAD.Vector(0, 0, 1),
        "XZ": FreeCAD.Vector(0, 1, 0),
        "YZ": FreeCAD.Vector(1, 0, 0),
    }
    normal = normal_map.get(plane.upper(), FreeCAD.Vector(0, 0, 1))
    mirrored = shape.mirror(origin, normal)

    feat = doc.addObject("Part::Feature", name)
    feat.Label = name
    feat.Shape = mirrored
    try:
        obj.Visibility = False
    except Exception:
        pass
    return {
        "tool": "mirror",
        "object": feat.Name,
        "source": target,
        "plane": plane.upper(),
        "type": "Part::Feature",
    }
