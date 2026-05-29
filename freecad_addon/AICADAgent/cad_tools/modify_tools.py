# modify_tools.py — Modification tools: modify_param, delete_object


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
