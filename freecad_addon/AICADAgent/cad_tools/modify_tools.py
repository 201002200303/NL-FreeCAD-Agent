# modify_tools.py — Modification tools: modify_param, delete_object, set_placement

from AICADAgent.cad_tools._helpers import apply_placement


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
    """Delete an object from the document. Missing target is a no-op."""
    name = str(target or "").strip()
    if not name:
        return {"tool": "delete_object", "object": "", "deleted": False}
    obj = doc.getObject(name)
    if obj is None:
        return {"tool": "delete_object", "object": name, "deleted": False}
    doc.removeObject(name)
    return {"tool": "delete_object", "object": name, "deleted": True}


def set_placement(doc, target="", pos_x=0, pos_y=0, pos_z=0,
                  rot_x=0, rot_y=0, rot_z=0):
    """Set the position (and optional rotation) of an object."""
    obj = doc.getObject(target)
    if obj is None:
        raise ValueError(f"Object not found: {target}")
    apply_placement(obj, pos_x, pos_y, pos_z, rot_x, rot_y, rot_z)
    return {
        "tool": "set_placement",
        "object": target,
        "position": [pos_x, pos_y, pos_z],
        "rotation": [rot_x, rot_y, rot_z],
    }
