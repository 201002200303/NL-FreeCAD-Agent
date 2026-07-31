# primitive_tools.py — Basic Part primitives (Box, Cylinder, Sphere, Cone, Torus)

import Part

from AICADAgent.cad_tools._helpers import apply_placement

_SUPPORTED_UNITS = {"mm", ""}


def _check_unit(unit: str) -> None:
    if unit not in _SUPPORTED_UNITS:
        raise ValueError(f"Unsupported unit '{unit}': only mm is supported")


def create_box(doc, name="Box", length=10, width=10, height=10, unit="mm",
               pos_x=0, pos_y=0, pos_z=0):
    """Create a Part::Box in the given document with optional position."""
    _check_unit(unit)
    if float(length) <= 0 or float(width) <= 0 or float(height) <= 0:
        raise ValueError(f"Box dimensions must be positive, got {length}x{width}x{height}")
    box = doc.addObject("Part::Box", name)
    box.Length = length
    box.Width = width
    box.Height = height
    box.Label = name
    apply_placement(box, pos_x, pos_y, pos_z)
    return {"tool": "create_box", "object": box.Name, "label": box.Label, "type": "Part::Box"}


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
                pos_x=0, pos_y=0, pos_z=0):
    """Create a Part::Cone. Reference point is center of bottom face."""
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
    apply_placement(cone, pos_x, pos_y, pos_z)
    return {"tool": "create_cone", "object": cone.Name, "label": cone.Label, "type": "Part::Cone"}


def create_torus(doc, name="Torus", radius1=20, radius2=5, unit="mm",
                 pos_x=0, pos_y=0, pos_z=0):
    """Create a Part::Torus. radius1=major, radius2=minor."""
    _check_unit(unit)
    if float(radius1) <= 0 or float(radius2) <= 0:
        raise ValueError(f"Torus radii must be positive, got R={radius1} r={radius2}")
    if float(radius2) >= float(radius1):
        raise ValueError(f"Torus minor radius must be < major radius, got R={radius1} r={radius2}")
    torus = doc.addObject("Part::Torus", name)
    torus.Radius1 = radius1
    torus.Radius2 = radius2
    torus.Label = name
    apply_placement(torus, pos_x, pos_y, pos_z)
    return {"tool": "create_torus", "object": torus.Name, "label": torus.Label, "type": "Part::Torus"}
