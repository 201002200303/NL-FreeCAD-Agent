# export_tools.py — Export tools: STEP, STL, FCStd save
# API ref: TopoShape.exportStep / exportStl

import Mesh

from AICADAgent.cad_tools._helpers import get_object, get_shape


def save_fcstd(doc, filepath=""):
    """Save the FreeCAD document to the given path."""
    doc.saveAs(filepath)
    return {"tool": "save_fcstd", "filepath": filepath}


def export_step(doc, target="", filepath=""):
    """Export target shape to STEP file."""
    obj = get_object(doc, target)
    get_shape(obj).exportStep(filepath)
    return {"tool": "export_step", "object": target, "filepath": filepath}


def export_stl(doc, target="", filepath="", tolerance=0.1):
    """Export target shape to STL mesh file."""
    if float(tolerance) <= 0:
        raise ValueError(f"Tolerance must be positive, got {tolerance}")
    obj = get_object(doc, target)
    shape = get_shape(obj)
    # Prefer native TopoShape export (FreeCAD Part API)
    if hasattr(shape, "exportStl"):
        shape.exportStl(filepath)
    else:
        mesh = Mesh.Mesh()
        mesh.addFacets(shape.tessellate(float(tolerance))[0])
        mesh.write(filepath)
    return {"tool": "export_stl", "object": target, "filepath": filepath, "tolerance": tolerance}
