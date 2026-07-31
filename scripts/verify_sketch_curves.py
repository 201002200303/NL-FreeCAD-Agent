"""Unit-test sketch helper logic without FreeCAD runtime."""
import importlib.util
import sys
import types


def _load_sketch_tools():
    fc = types.ModuleType("FreeCAD")

    class Vector:
        def __init__(self, x=0, y=0, z=0):
            self.x, self.y, self.z = float(x), float(y), float(z)

    class Rotation:
        def __init__(self, *a, **k):
            pass

    class Placement:
        def __init__(self, *a, **k):
            pass

    fc.Vector = Vector
    fc.Rotation = Rotation
    fc.Placement = Placement
    sys.modules["FreeCAD"] = fc

    part = types.ModuleType("Part")

    class LineSegment:
        def __init__(self, *a, **k):
            pass

    class Circle:
        def __init__(self, *a, **k):
            pass

    class ArcOfCircle:
        def __init__(self, *a, **k):
            pass

    class BSplineCurve:
        Degree = 3

        def interpolate(self, *a, **k):
            pass

        def buildFromPoles(self, *a, **k):
            pass

        def increaseDegree(self, *a, **k):
            pass

    part.LineSegment = LineSegment
    part.Circle = Circle
    part.ArcOfCircle = ArcOfCircle
    part.BSplineCurve = BSplineCurve
    sys.modules["Part"] = part

    sketcher = types.ModuleType("Sketcher")

    class Constraint:
        def __init__(self, *a, **k):
            pass

    sketcher.Constraint = Constraint
    sys.modules["Sketcher"] = sketcher

    sys.modules["AICADAgent"] = types.ModuleType("AICADAgent")
    sys.modules["AICADAgent.cad_tools"] = types.ModuleType("AICADAgent.cad_tools")
    helpers = types.ModuleType("AICADAgent.cad_tools._helpers")
    helpers.get_object = lambda doc, name: doc[name]
    sys.modules["AICADAgent.cad_tools._helpers"] = helpers

    path = r"D:\project_main\NL-FreeCAD-Agent\freecad_addon\AICADAgent\cad_tools\sketch_tools.py"
    spec = importlib.util.spec_from_file_location("sketch_tools_ut", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    sk = _load_sketch_tools()
    assert sk._normalize_points([[0, 0], [1, 2]]) == [(0.0, 0.0), (1.0, 2.0)]
    assert sk._normalize_points([{"x": 1, "y": 2}]) == [(1.0, 2.0)]
    try:
        sk._normalize_points(["bad"])
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    # polyline with mock sketch
    class FakeSketch:
        def __init__(self):
            self.geos = []
            self.constraints = []

        def addGeometry(self, geo, construction=False):
            gid = len(self.geos)
            self.geos.append(geo)
            return gid

        def addConstraint(self, c):
            self.constraints.append(c)
            return len(self.constraints) - 1

    doc = {"S1": FakeSketch()}
    result = sk.sketch_add_polyline(doc, sketch="S1", points=[[0, 0], [10, 0], [10, 10]], closed=False)
    assert result["geometry_ids"] == [0, 1]
    assert len(doc["S1"].constraints) == 1  # one coincident between segments

    result2 = sk.sketch_add_arc(doc, sketch="S1", mode="three_point", x1=0, y1=0, x2=5, y2=5, x3=10, y3=0)
    assert result2["geometry_id"] == 2

    result3 = sk.sketch_add_bspline(doc, sketch="S1", points=[[0, 0], [5, 5], [10, 0]], mode="interpolate")
    assert result3["geometry_id"] == 3
    print("OK: arc / polyline / bspline helpers")


if __name__ == "__main__":
    main()
