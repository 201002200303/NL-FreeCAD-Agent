# _helpers.py — Shared helpers for CAD tool functions
#
# 拓扑命名说明 (FreeCAD Topological Naming Problem):
# - 每个 Shape 的子元素按 OCCT 顺序编号: Edge1..EdgeN, Face1..FaceN, Vertex1..VertexN (1-based)
# - 简单 Part::Box 稳定有 12 条边、6 个面；fillet/pad/boolean 后编号会重排
# - 推荐: 操作前 list_topology 获取当前编号，或使用语义选择器 (top/bottom/+Z 等)

import math
import FreeCAD


TOL = 1e-3


def get_object(doc, name: str):
    obj = doc.getObject(name)
    if obj is None:
        raise ValueError(f"Object not found: {name}")
    return obj


def get_shape(obj):
    if not hasattr(obj, "Shape"):
        raise ValueError(f"Object '{obj.Name}' has no Shape property")
    shape = obj.Shape
    if shape.isNull():
        raise ValueError(f"Object '{obj.Name}' has empty Shape")
    return shape


def apply_axis_rotation(rot_x=0, rot_y=0, rot_z=0):
    """Compose rotations around fixed X/Y/Z axes (degrees), not yaw-pitch-roll."""
    rot = FreeCAD.Rotation()
    for axis, angle in (
        (FreeCAD.Vector(1, 0, 0), rot_x),
        (FreeCAD.Vector(0, 1, 0), rot_y),
        (FreeCAD.Vector(0, 0, 1), rot_z),
    ):
        if angle:
            rot = rot * FreeCAD.Rotation(axis, float(angle))
    return rot


def apply_placement(obj, pos_x=0, pos_y=0, pos_z=0, rot_x=0, rot_y=0, rot_z=0):
    """Set absolute position/rotation. Always applies, so all-zero args reset
    the object back to the origin / identity rotation (set_placement semantics)."""
    obj.Placement.Base = FreeCAD.Vector(float(pos_x), float(pos_y), float(pos_z))
    obj.Placement.Rotation = apply_axis_rotation(rot_x, rot_y, rot_z)


def assign_shape_result(doc, target_name: str, new_shape, result_name=None):
    """Apply a computed shape result back to the document.

    - Part::Feature + same result name: overwrite Shape in-place.
    - Part::Feature + different result name: create new Part::Feature, hide source.
    - Parametric objects (Part::Cylinder, Part::Box, etc.): create a new
      Part::Feature to hold the result, hide the parametric source (its
      recompute would overwrite the fillet/chamfer), and use identity
      Placement because the geometry already carries world coordinates.
    """
    target = get_object(doc, target_name)
    out_name = result_name or target_name

    in_place = (
        hasattr(target, "Shape")
        and target.TypeId == "Part::Feature"
        and out_name == target_name
    )
    if in_place:
        target.Shape = new_shape
        return target

    feat = doc.addObject("Part::Feature", out_name)
    feat.Label = out_name
    feat.Shape = new_shape

    try:
        target.Visibility = False
    except Exception:
        pass

    return feat


def _edge_length(edge) -> float:
    return edge.Length


def _edge_center(edge):
    p0 = edge.Vertexes[0].Point
    p1 = edge.Vertexes[-1].Point
    return FreeCAD.Vector((p0.x + p1.x) / 2, (p0.y + p1.y) / 2, (p0.z + p1.z) / 2)


def _face_center_normal(face):
    u, v = face.Surface.parameter(face.CenterOfMass)
    normal = face.normalAt(u, v)
    return face.CenterOfMass, normal


def _classify_face(normal):
    nx, ny, nz = abs(normal.x), abs(normal.y), abs(normal.z)
    if nz >= nx and nz >= ny:
        return "+Z" if normal.z > 0 else "-Z"
    if ny >= nx and ny >= nz:
        return "+Y" if normal.y > 0 else "-Y"
    return "+X" if normal.x > 0 else "-X"


def _classify_edge(edge):
    p0 = edge.Vertexes[0].Point
    p1 = edge.Vertexes[-1].Point
    dx, dy, dz = abs(p1.x - p0.x), abs(p1.y - p0.y), abs(p1.z - p0.z)
    if dz > dx and dz > dy:
        return "vertical"
    if dz < TOL:
        return "horizontal"
    return "other"


def analyze_topology(shape) -> dict:
    """Return structured topology info for LLM / list_topology tool."""
    bb = shape.BoundBox
    z_min, z_max = bb.ZMin, bb.ZMax
    y_min, y_max = bb.YMin, bb.YMax
    x_min, x_max = bb.XMin, bb.XMax

    faces = []
    for i, face in enumerate(shape.Faces, start=1):
        center, normal = _face_center_normal(face)
        zone = _classify_face(normal)
        faces.append({
            "index": i,
            "name": f"Face{i}",
            "area": round(face.Area, 4),
            "center": [round(center.x, 3), round(center.y, 3), round(center.z, 3)],
            "normal": [round(normal.x, 3), round(normal.y, 3), round(normal.z, 3)],
            "zone": zone,
        })

    edges = []
    for i, edge in enumerate(shape.Edges, start=1):
        c = _edge_center(edge)
        edges.append({
            "index": i,
            "name": f"Edge{i}",
            "length": round(_edge_length(edge), 4),
            "center": [round(c.x, 3), round(c.y, 3), round(c.z, 3)],
            "kind": _classify_edge(edge),
            "on_top": abs(c.z - z_max) < TOL,
            "on_bottom": abs(c.z - z_min) < TOL,
        })

    return {
        "edge_count": len(edges),
        "face_count": len(faces),
        "vertex_count": len(shape.Vertexes),
        "bbox": {
            "x": [round(x_min, 3), round(x_max, 3)],
            "y": [round(y_min, 3), round(y_max, 3)],
            "z": [round(z_min, 3), round(z_max, 3)],
        },
        "faces": faces,
        "edges": edges,
        "hint": (
            "边/面编号为当前 Shape 的 1-based 索引 (Edge1, Face3)。"
            "修改几何后编号可能变化；优先用语义选择器或操作前 list_topology。"
        ),
    }


def _parse_face_index(shape, token: str) -> int:
    token = token.strip()
    if token.lower().startswith("face"):
        return int(token[4:]) - 1
    return int(token) - 1


def _parse_edge_index(shape, token: str) -> int:
    token = token.strip()
    if token.lower().startswith("edge"):
        return int(token[4:]) - 1
    return int(token) - 1


def select_faces(shape, face_selector: str = "all"):
    """Select faces by index (Face3), zone (+Z/-Z/+X...), or semantic top/bottom/front/back/left/right."""
    if not face_selector or face_selector == "all":
        return shape.Faces

    sel = face_selector.strip()
    if sel.startswith("Face") or sel.isdigit():
        idx = _parse_face_index(shape, sel)
        return [shape.Faces[idx]]

    zone_map = {
        "top": "+Z", "bottom": "-Z",
        "front": "+Y", "back": "-Y",
        "right": "+X", "left": "-X",
    }
    zone = zone_map.get(sel.lower(), sel.upper())
    result = []
    for face in shape.Faces:
        _, normal = _face_center_normal(face)
        if _classify_face(normal) == zone:
            result.append(face)
    return result


def select_edges(shape, edge_selector: str = "all", face_selector: str = None):
    """
    Select edges by:
      - all
      - top / bottom / vertical / horizontal
      - longest / shortest
      - Edge1,Edge3 or 1,3
      - face:Face3 (edges belonging to that face)
      - zone:+Z (edges whose center lies on bbox face of that zone)
    """
    if edge_selector == "all" and not face_selector:
        return shape.Edges

    if face_selector:
        faces = select_faces(shape, face_selector)
        edge_set = []
        seen = set()
        for face in faces:
            for edge in face.Edges:
                key = edge.hashCode(100000000)
                if key not in seen:
                    seen.add(key)
                    edge_set.append(edge)
        if edge_selector == "all":
            return edge_set
        shape_edges = edge_set
    else:
        shape_edges = list(shape.Edges)

    if edge_selector == "all":
        return shape_edges

    bb = shape.BoundBox

    if edge_selector == "top":
        z_max = bb.ZMax
        return [e for e in shape_edges
                if abs(_edge_center(e).z - z_max) < TOL and _classify_edge(e) == "horizontal"]
    if edge_selector == "bottom":
        z_min = bb.ZMin
        return [e for e in shape_edges
                if abs(_edge_center(e).z - z_min) < TOL and _classify_edge(e) == "horizontal"]
    if edge_selector == "vertical":
        return [e for e in shape_edges if _classify_edge(e) == "vertical"]
    if edge_selector == "horizontal":
        return [e for e in shape_edges if _classify_edge(e) == "horizontal"]
    if edge_selector == "longest":
        return [max(shape_edges, key=_edge_length)]
    if edge_selector == "shortest":
        return [min(shape_edges, key=_edge_length)]

    if edge_selector.startswith("zone:"):
        zone = edge_selector.split(":", 1)[1].upper()
        limits = {
            "+Z": ("z", bb.ZMax), "-Z": ("z", bb.ZMin),
            "+Y": ("y", bb.YMax), "-Y": ("y", bb.YMin),
            "+X": ("x", bb.XMax), "-X": ("x", bb.XMin),
        }
        axis, val = limits.get(zone, ("z", bb.ZMax))
        result = []
        for e in shape_edges:
            c = _edge_center(e)
            coord = getattr(c, axis)
            if abs(coord - val) < TOL:
                result.append(e)
        return result

    edges = []
    for token in edge_selector.split(","):
        token = token.strip()
        if not token:
            continue
        idx = _parse_edge_index(shape, token)
        edges.append(shape.Edges[idx])
    return edges
