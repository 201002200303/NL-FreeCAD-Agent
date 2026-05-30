# assembly_tools.py — Assembly constraints (FreeCAD 1.0+ Assembly workbench)
# Note: Assembly API varies by workbench (Assembly vs Assembly3).
# These tools use basic placement-based mating as a portable fallback.

import FreeCAD

from AICADAgent.cad_tools._helpers import get_object


def create_assembly(doc, name="Assembly"):
    """Create assembly container. Uses App::DocumentObjectGroup if Assembly workbench unavailable."""
    try:
        asm = doc.addObject("Assembly::AssemblyObject", name)
    except Exception:
        asm = doc.addObject("App::DocumentObjectGroup", name)
    asm.Label = name
    return {"tool": "create_assembly", "object": asm.Name, "type": asm.TypeId}


def add_to_assembly(doc, assembly="", part="", name=None):
    """Add part link to assembly group."""
    asm = get_object(doc, assembly)
    part_obj = get_object(doc, part)
    if hasattr(asm, "addObject"):
        asm.addObject(part_obj)
    elif hasattr(doc, "addObject"):
        link_name = name or f"{part}_Link"
        try:
            link = doc.addObject("App::Link", link_name)
            link.LinkedObject = part_obj
            asm.addObject(link)
            return {"tool": "add_to_assembly", "assembly": assembly, "link": link.Name, "part": part}
        except Exception:
            asm.addObject(part_obj)
    return {"tool": "add_to_assembly", "assembly": assembly, "part": part}


def mate_planes(doc, assembly="", part1="", part2="", plane1="+Z", plane2="-Z",
                offset_x=0, offset_y=0, offset_z=0):
    """
    Mate two parts by aligning bbox face normals (portable fallback).
    For precise mates use list_topology + set_placement on each part.
    """
    p1 = get_object(doc, part1)
    p2 = get_object(doc, part2)
    bb1 = p1.Shape.BoundBox if hasattr(p1, "Shape") else None
    bb2 = p2.Shape.BoundBox if hasattr(p2, "Shape") else None
    if not bb1 or not bb2:
        raise ValueError("Both parts must have Shape for plane mating")

    normal_map = {
        "+Z": FreeCAD.Vector(0, 0, 1), "-Z": FreeCAD.Vector(0, 0, -1),
        "+Y": FreeCAD.Vector(0, 1, 0), "-Y": FreeCAD.Vector(0, -1, 0),
        "+X": FreeCAD.Vector(1, 0, 0), "-X": FreeCAD.Vector(-1, 0, 0),
    }
    n1 = normal_map.get(plane1.upper(), FreeCAD.Vector(0, 0, 1))
    n2 = normal_map.get(plane2.upper(), FreeCAD.Vector(0, 0, -1))

    c1 = bb1.Center
    c2 = bb2.Center
    delta = c1 - c2 + FreeCAD.Vector(float(offset_x), float(offset_y), float(offset_z))
    plm = p2.Placement
    plm.Base = plm.Base + delta
    p2.Placement = plm

    return {
        "tool": "mate_planes",
        "assembly": assembly,
        "part1": part1,
        "part2": part2,
        "plane1": plane1,
        "plane2": plane2,
        "offset": [offset_x, offset_y, offset_z],
        "note": "Placement-based mate; for true constraints use FreeCAD Assembly workbench GUI",
    }


def mate_coaxial(doc, assembly="", part1="", part2="", axis="Z", offset_x=0, offset_y=0, offset_z=0):
    """Coaxial mate fallback: align centers and share axis."""
    p1 = get_object(doc, part1)
    p2 = get_object(doc, part2)
    c1 = p1.Shape.BoundBox.Center
    c2 = p2.Shape.BoundBox.Center
    delta = c1 - c2 + FreeCAD.Vector(float(offset_x), float(offset_y), float(offset_z))
    plm = p2.Placement
    plm.Base = plm.Base + delta
    p2.Placement = plm
    return {
        "tool": "mate_coaxial",
        "assembly": assembly,
        "part1": part1,
        "part2": part2,
        "axis": axis.upper(),
    }
