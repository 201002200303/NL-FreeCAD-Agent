# query_tools.py — Topology query tools for precise sub-element selection

from AICADAgent.cad_tools._helpers import get_object, get_shape, analyze_topology


def list_topology(doc, target=""):
    """List faces/edges with indices, centers, normals — use before fillet/chamfer/pad-on-face."""
    obj = get_object(doc, target)
    shape = get_shape(obj)
    info = analyze_topology(shape)
    info["tool"] = "list_topology"
    info["object"] = obj.Name
    info["type"] = obj.TypeId
    return info
