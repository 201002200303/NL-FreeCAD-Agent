# primitive_tools.py — Basic Part primitives (Box, Cylinder, Sphere, Cone, Torus)

import Part


def create_box(doc, name="Box", length=10, width=10, height=10, unit="mm"):
    """Create a Part::Box in the given document."""
    box = doc.addObject("Part::Box", name)
    box.Length = length
    box.Width = width
    box.Height = height
    box.Label = name
    return {"tool": "create_box", "object": box.Name, "label": box.Label, "type": "Part::Box"}


def create_cylinder(doc, name="Cylinder", radius=10, height=20, unit="mm"):
    """Create a Part::Cylinder in the given document."""
    cyl = doc.addObject("Part::Cylinder", name)
    cyl.Radius = radius
    cyl.Height = height
    cyl.Label = name
    return {"tool": "create_cylinder", "object": cyl.Name, "label": cyl.Label, "type": "Part::Cylinder"}
