# sketch_tools.py — Sketcher operations
# API ref: https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Sketcher_scripting.md

import FreeCAD
import Part
import Sketcher

from AICADAgent.cad_tools._helpers import get_object


_PLANE_MAP = {
    "XY": (FreeCAD.Vector(0, 0, 0), FreeCAD.Rotation(0, 0, 0)),
    "XZ": (FreeCAD.Vector(0, 0, 0), FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 90)),
    "YZ": (FreeCAD.Vector(0, 0, 0), FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 90)),
}


def create_body(doc, name="Body"):
    """Create a PartDesign Body container."""
    body = doc.addObject("PartDesign::Body", name)
    body.Label = name
    return {"tool": "create_body", "object": body.Name, "type": "PartDesign::Body"}


def create_sketch(doc, name="Sketch", plane="XY", body=None,
                  pos_x=0, pos_y=0, pos_z=0, map_mode="FlatFace"):
    """Create sketch on datum plane XY/XZ/YZ or inside a Body."""
    if body:
        container = get_object(doc, body)
        sketch = container.newObject("Sketcher::SketchObject", name)
    else:
        sketch = doc.addObject("Sketcher::SketchObject", name)
    sketch.Label = name

    base, rot = _PLANE_MAP.get(plane.upper(), _PLANE_MAP["XY"])
    sketch.Placement = FreeCAD.Placement(
        FreeCAD.Vector(float(pos_x), float(pos_y), float(pos_z)) + base,
        rot,
    )
    return {
        "tool": "create_sketch",
        "object": sketch.Name,
        "body": body,
        "plane": plane.upper(),
        "type": "Sketcher::SketchObject",
    }


def create_sketch_on_face(doc, name="Sketch", target="", face="Face1", body=None, map_mode="FlatFace"):
    """Attach sketch to an existing face (for pad-on-face workflow)."""
    target_obj = get_object(doc, target)
    face_idx = int(face.replace("Face", "")) - 1 if face.lower().startswith("face") else int(face) - 1

    if body:
        container = get_object(doc, body)
        sketch = container.newObject("Sketcher::SketchObject", name)
    else:
        sketch = doc.addObject("Sketcher::SketchObject", name)
    sketch.Label = name
    sketch.AttachmentSupport = [(target_obj, f"Face{face_idx + 1}")]
    sketch.MapMode = map_mode
    return {
        "tool": "create_sketch_on_face",
        "object": sketch.Name,
        "target": target,
        "face": f"Face{face_idx + 1}",
        "type": "Sketcher::SketchObject",
    }


def sketch_add_line(doc, sketch="", x1=0, y1=0, x2=10, y2=0):
    sk = get_object(doc, sketch)
    geo_id = sk.addGeometry(Part.LineSegment(
        FreeCAD.Vector(float(x1), float(y1), 0),
        FreeCAD.Vector(float(x2), float(y2), 0),
    ), False)
    return {"tool": "sketch_add_line", "sketch": sketch, "geometry_id": geo_id}


def sketch_add_rect(doc, sketch="", x=0, y=0, width=10, height=10):
    sk = get_object(doc, sketch)
    x, y, w, h = float(x), float(y), float(width), float(height)
    ids = []
    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    for i in range(4):
        ids.append(sk.addGeometry(Part.LineSegment(
            FreeCAD.Vector(pts[i][0], pts[i][1], 0),
            FreeCAD.Vector(pts[i + 1][0], pts[i + 1][1], 0),
        ), False))
    return {"tool": "sketch_add_rect", "sketch": sketch, "geometry_ids": ids}


def sketch_add_circle(doc, sketch="", center_x=0, center_y=0, radius=5):
    sk = get_object(doc, sketch)
    geo_id = sk.addGeometry(Part.Circle(
        FreeCAD.Vector(float(center_x), float(center_y), 0),
        FreeCAD.Vector(0, 0, 1),
        float(radius),
    ), False)
    return {"tool": "sketch_add_circle", "sketch": sketch, "geometry_id": geo_id}


def sketch_add_constraint(doc, sketch="", constraint_type="Coincident", geo1=0, point1=1, geo2=1, point2=1):
    """Add sketch constraint. geo/point are 0-based indices per Sketcher API."""
    sk = get_object(doc, sketch)
    if geo2 is None:
        cid = sk.addConstraint(Sketcher.Constraint(constraint_type, int(geo1), int(point1)))
    else:
        cid = sk.addConstraint(Sketcher.Constraint(
            constraint_type, int(geo1), int(point1), int(geo2), int(point2),
        ))
    return {"tool": "sketch_add_constraint", "sketch": sketch, "constraint_id": cid}
