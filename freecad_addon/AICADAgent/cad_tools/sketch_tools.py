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


def _parse_face_index(face, face_count=None):
    token = str(face).strip()
    if token.lower().startswith("face"):
        token = token[4:]
    try:
        idx = int(token) - 1
    except ValueError:
        raise ValueError(f"Invalid face reference: '{face}' (expected FaceN or N)")
    if idx < 0:
        raise ValueError(f"Invalid face reference: '{face}'")
    if face_count is not None and idx >= face_count:
        raise ValueError(f"Face '{face}' out of range: shape has {face_count} face(s)")
    return idx


def create_sketch_on_face(doc, name="Sketch", target="", face="Face1", body=None, map_mode="FlatFace"):
    """Attach sketch to an existing face (for pad-on-face workflow)."""
    target_obj = get_object(doc, target)
    face_count = len(target_obj.Shape.Faces) if hasattr(target_obj, "Shape") else None
    face_idx = _parse_face_index(face, face_count)

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
    if float(radius) <= 0:
        raise ValueError(f"Circle radius must be positive, got {radius}")
    geo_id = sk.addGeometry(Part.Circle(
        FreeCAD.Vector(float(center_x), float(center_y), 0),
        FreeCAD.Vector(0, 0, 1),
        float(radius),
    ), False)
    return {"tool": "sketch_add_circle", "sketch": sketch, "geometry_id": geo_id}


def sketch_add_arc(
    doc,
    sketch="",
    mode="three_point",
    x1=0, y1=0, x2=5, y2=5, x3=10, y3=0,
    center_x=0, center_y=0, radius=10,
    start_angle=0, end_angle=180,
):
    """Add a circular arc via FreeCAD Sketcher API.

    Official pattern (GUI console / forum):
      sketch.addGeometry(Part.ArcOfCircle(p1, p2, p3), False)
    or:
      sketch.addGeometry(Part.ArcOfCircle(Part.Circle(c, n, r), a1, a2), False)
    Angles are degrees in this tool (converted to radians for Part API).
    """
    import math

    sk = get_object(doc, sketch)
    mode = str(mode or "three_point").strip().lower()
    if mode in {"three_point", "3point", "points"}:
        arc = Part.ArcOfCircle(
            FreeCAD.Vector(float(x1), float(y1), 0),
            FreeCAD.Vector(float(x2), float(y2), 0),
            FreeCAD.Vector(float(x3), float(y3), 0),
        )
    elif mode in {"center", "center_angles", "polar"}:
        if float(radius) <= 0:
            raise ValueError(f"Arc radius must be positive, got {radius}")
        circle = Part.Circle(
            FreeCAD.Vector(float(center_x), float(center_y), 0),
            FreeCAD.Vector(0, 0, 1),
            float(radius),
        )
        arc = Part.ArcOfCircle(
            circle,
            math.radians(float(start_angle)),
            math.radians(float(end_angle)),
        )
    else:
        raise ValueError(f"Unsupported arc mode '{mode}': use three_point or center")
    geo_id = sk.addGeometry(arc, False)
    return {
        "tool": "sketch_add_arc",
        "sketch": sketch,
        "geometry_id": geo_id,
        "mode": mode,
    }


def sketch_add_polyline(doc, sketch="", points=None, closed=False):
    """Add a polyline as consecutive Part.LineSegment edges (Sketcher polyline style).

    Official pattern: chain LineSegment via addGeometry, then Coincident on shared
    endpoints (same as FreeCAD Sketcher Create Polyline).
    points: [[x,y], ...] or [{"x":..,"y":..}, ...] — at least 2 points.
    """
    sk = get_object(doc, sketch)
    pts = _normalize_points(points)
    if len(pts) < 2:
        raise ValueError("Polyline needs at least 2 points")

    if closed and pts[0] != pts[-1]:
        pts = pts + [pts[0]]

    ids = []
    for i in range(len(pts) - 1):
        p0, p1 = pts[i], pts[i + 1]
        if p0 == p1:
            continue
        geo_id = sk.addGeometry(Part.LineSegment(
            FreeCAD.Vector(p0[0], p0[1], 0),
            FreeCAD.Vector(p1[0], p1[1], 0),
        ), False)
        ids.append(geo_id)

    if not ids:
        raise ValueError("Polyline produced no segments (duplicate points?)")

    # Connect consecutive segments at shared endpoints (1=start, 2=end)
    for i in range(len(ids) - 1):
        sk.addConstraint(Sketcher.Constraint("Coincident", ids[i], 2, ids[i + 1], 1))
    if closed and len(ids) >= 2:
        sk.addConstraint(Sketcher.Constraint("Coincident", ids[-1], 2, ids[0], 1))

    return {
        "tool": "sketch_add_polyline",
        "sketch": sketch,
        "geometry_ids": ids,
        "closed": bool(closed),
        "point_count": len(pts) - (1 if closed and pts[0] == pts[-1] else 0),
    }


def sketch_add_bspline(
    doc,
    sketch="",
    points=None,
    mode="interpolate",
    degree=3,
    periodic=False,
):
    """Add a B-spline to the sketch.

    Official Part API:
      c = Part.BSplineCurve(); c.interpolate(points)
      c = Part.BSplineCurve(); c.buildFromPoles(points, periodic, degree)
      sketch.addGeometry(c, False)
    mode:
      - interpolate: curve passes through points (recommended for profiles)
      - poles: points are control poles
    """
    sk = get_object(doc, sketch)
    pts = _normalize_points(points)
    if len(pts) < 2:
        raise ValueError("BSpline needs at least 2 points")
    vectors = [FreeCAD.Vector(p[0], p[1], 0) for p in pts]
    mode = str(mode or "interpolate").strip().lower()
    deg = int(degree)
    if deg < 1:
        raise ValueError(f"BSpline degree must be >= 1, got {degree}")

    curve = Part.BSplineCurve()
    if mode in {"interpolate", "through", "fit"}:
        # PeriodicFlag kw exists on FreeCAD Part.BSplineCurve.interpolate
        try:
            curve.interpolate(vectors, PeriodicFlag=bool(periodic))
        except TypeError:
            curve.interpolate(vectors)
        if deg > curve.Degree:
            try:
                curve.increaseDegree(deg)
            except Exception:
                pass
    elif mode in {"poles", "control", "control_points"}:
        # buildFromPoles(poles, periodic=False, degree=3, interpolate=False)
        curve.buildFromPoles(vectors, bool(periodic), min(deg, len(vectors) - 1))
    else:
        raise ValueError(f"Unsupported bspline mode '{mode}': use interpolate or poles")

    geo_id = sk.addGeometry(curve, False)
    return {
        "tool": "sketch_add_bspline",
        "sketch": sketch,
        "geometry_id": geo_id,
        "mode": mode,
        "degree": curve.Degree if hasattr(curve, "Degree") else deg,
        "point_count": len(pts),
        "periodic": bool(periodic),
    }


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


def _normalize_points(points) -> list[tuple[float, float]]:
    """Accept [[x,y], ...] or [{"x":..,"y":..}, ...] or [{"X":..,"Y":..}]."""
    if not points:
        return []
    if not isinstance(points, (list, tuple)):
        raise ValueError("points must be a list of [x,y] or {x,y}")
    out: list[tuple[float, float]] = []
    for i, item in enumerate(points):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out.append((float(item[0]), float(item[1])))
        elif isinstance(item, dict):
            if "x" in item and "y" in item:
                out.append((float(item["x"]), float(item["y"])))
            elif "X" in item and "Y" in item:
                out.append((float(item["X"]), float(item["Y"])))
            else:
                raise ValueError(f"points[{i}] dict needs x/y keys, got {item}")
        else:
            raise ValueError(f"points[{i}] must be [x,y] or {{x,y}}, got {type(item).__name__}")
    return out
