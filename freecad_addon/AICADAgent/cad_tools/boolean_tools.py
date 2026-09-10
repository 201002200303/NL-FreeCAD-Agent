# boolean_tools.py — Boolean operations (fuse, cut, common)
# API ref: https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Topological_data_scripting.md

import FreeCAD

from AICADAgent.cad_tools._helpers import get_object, get_world_shape, remove_objects


def _boolean_result(doc, name, base_name, tool_name, op, tool_label):
    base_obj = get_object(doc, base_name)
    tool_obj = get_object(doc, tool_name)
    result_shape = op(get_world_shape(base_obj), get_world_shape(tool_obj))

    feat = doc.addObject("Part::Feature", name)
    feat.Label = name
    feat.Shape = result_shape

    # fuse/cut 后删源件，避免 Visibility=False 失败留下幽灵实体（多余扇叶等）
    removed = remove_objects(doc, [base_name, tool_name])

    return {
        "tool": tool_label,
        "object": feat.Name,
        "label": feat.Label,
        "type": "Part::Feature",
        "base": base_name,
        "tool_object": tool_name,
        "removed": removed,
        "source": base_name,
    }


def boolean_fuse(doc, name="Fuse", base="", tool=""):
    return _boolean_result(doc, name, base, tool, lambda a, b: a.fuse(b), "boolean_fuse")


def boolean_cut(doc, name="Cut", base="", tool=""):
    return _boolean_result(doc, name, base, tool, lambda a, b: a.cut(b), "boolean_cut")


def boolean_common(doc, name="Common", base="", tool=""):
    return _boolean_result(doc, name, base, tool, lambda a, b: a.common(b), "boolean_common")
