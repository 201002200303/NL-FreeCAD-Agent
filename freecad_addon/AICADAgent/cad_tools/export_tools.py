# export_tools.py — Export tools: STEP, STL, FCStd save
# API ref: TopoShape.exportStep / exportStl

import Mesh
import Part

from AICADAgent.cad_tools._helpers import get_object, get_shape
from AICADAgent.export_selection import select_export_names


def save_fcstd(doc, filepath=""):
    """Save the FreeCAD document to the given path."""
    doc.saveAs(filepath)
    return {"tool": "save_fcstd", "filepath": filepath}


def _export_shape(doc, target):
    """把 target（空 / 单名 / 名字列表）解析成**一个** Shape 用于导出。

    多个对象时组合成 Compound：不布尔、不改文档，只是让导出落在同一文件里。
    """
    objects = [
        (obj.Name, obj.TypeId, bool(getattr(obj, "Visibility", True)))
        for obj in doc.Objects
    ]
    names = select_export_names(target, objects)
    if len(names) == 1:
        return get_shape(get_object(doc, names[0])), names
    shapes = [get_shape(get_object(doc, name)) for name in names]
    return Part.makeCompound(shapes), names


def export_step(doc, target="", filepath=""):
    """Export target object(s) to STEP file. Empty target = whole document."""
    shape, names = _export_shape(doc, target)
    shape.exportStep(filepath)
    return {
        "tool": "export_step",
        "object": names[0] if len(names) == 1 else names,
        "objects": names,
        "filepath": filepath,
    }


def export_stl(doc, target="", filepath="", tolerance=0.1):
    """Export target object(s) to STL mesh file. Empty target = whole document."""
    if float(tolerance) <= 0:
        raise ValueError(f"Tolerance must be positive, got {tolerance}")
    shape, names = _export_shape(doc, target)
    # Prefer native TopoShape export (FreeCAD Part API)
    if hasattr(shape, "exportStl"):
        shape.exportStl(filepath)
    else:
        mesh = Mesh.Mesh()
        mesh.addFacets(shape.tessellate(float(tolerance))[0])
        mesh.write(filepath)
    return {
        "tool": "export_stl",
        "object": names[0] if len(names) == 1 else names,
        "objects": names,
        "filepath": filepath,
        "tolerance": tolerance,
    }
