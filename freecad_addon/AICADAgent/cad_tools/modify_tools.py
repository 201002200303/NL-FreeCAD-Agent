# modify_tools.py — Modification tools: modify_param, delete_object, set_placement

import FreeCAD


def modify_param(doc, target="", param="", value=0):
    """Modify a parameter of an existing object."""
    obj = doc.getObject(target)
    if obj is None:
        raise ValueError(f"Object not found: {target}")
    if not hasattr(obj, param):
        raise ValueError(f"Object '{target}' has no parameter '{param}'")
    setattr(obj, param, value)
    return {"tool": "modify_param", "object": target, "param": param, "value": value}


def delete_object(doc, target=""):
    """Delete an object from the document."""
    obj = doc.getObject(target)
    if obj is None:
        raise ValueError(f"Object not found: {target}")
    doc.removeObject(target)
    return {"tool": "delete_object", "object": target}


def set_placement(doc, target="", pos_x=0, pos_y=0, pos_z=0,
                  rot_x=0, rot_y=0, rot_z=0):
    """Set the position (and optional rotation) of an object."""
    obj = doc.getObject(target)
    if obj is None:
        raise ValueError(f"Object not found: {target}")
    obj.Placement.Base = FreeCAD.Vector(pos_x, pos_y, pos_z)
    if rot_x != 0 or rot_y != 0 or rot_z != 0:
        obj.Placement.Rotation = FreeCAD.Rotation(rot_x, rot_y, rot_z)
    return {
        "tool": "set_placement",
        "object": target,
        "position": [pos_x, pos_y, pos_z],
    }
