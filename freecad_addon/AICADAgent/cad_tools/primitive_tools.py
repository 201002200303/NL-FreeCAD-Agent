# primitive_tools.py — Basic Part primitives (Box, Cylinder, Sphere, Cone, Torus)

import FreeCAD
import Part


def create_box(doc, name="Box", length=10, width=10, height=10, unit="mm",
               pos_x=0, pos_y=0, pos_z=0):
    """Create a Part::Box in the given document with optional position."""
    box = doc.addObject("Part::Box", name)
    box.Length = length
    box.Width = width
    box.Height = height
    box.Label = name
    apply_placement(box, pos_x, pos_y, pos_z)
    return {"tool": "create_box", "object": box.Name, "label": box.Label, "type": "Part::Box"}


def create_cylinder(doc, name="Cylinder", radius=10, height=20, unit="mm",
                    pos_x=0, pos_y=0, pos_z=0):
    """Create a Part::Cylinder in the given document with optional position."""
    cyl = doc.addObject("Part::Cylinder", name)
    cyl.Radius = radius
    cyl.Height = height
    cyl.Label = name
    apply_placement(cyl, pos_x, pos_y, pos_z)
    return {"tool": "create_cylinder", "object": cyl.Name, "label": cyl.Label, "type": "Part::Cylinder"}


def create_sphere(doc, name="Sphere", radius=10, unit="mm", pos_x=0, pos_y=0, pos_z=0):
    """Create a Part::Sphere. Reference point is sphere center."""
    sphere = doc.addObject("Part::Sphere", name)
    sphere.Radius = radius
    sphere.Label = name
    apply_placement(sphere, pos_x, pos_y, pos_z)
    return {"tool": "create_sphere", "object": sphere.Name, "label": sphere.Label, "type": "Part::Sphere"}


def create_cone(doc, name="Cone", radius1=10, radius2=0, height=20, unit="mm",
                pos_x=0, pos_y=0, pos_z=0):
    """Create a Part::Cone. Reference point is center of bottom face."""
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
    torus = doc.addObject("Part::Torus", name)
    torus.Radius1 = radius1
    torus.Radius2 = radius2
    torus.Label = name
    apply_placement(torus, pos_x, pos_y, pos_z)
    return {"tool": "create_torus", "object": torus.Name, "label": torus.Label, "type": "Part::Torus"}


def apply_placement(obj, pos_x=0, pos_y=0, pos_z=0):
    if pos_x != 0 or pos_y != 0 or pos_z != 0:
        obj.Placement.Base = FreeCAD.Vector(pos_x, pos_y, pos_z)
