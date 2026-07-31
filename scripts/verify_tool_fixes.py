# Verify tool fixes by loading modules with a stubbed FreeCAD environment.
# FreeCAD itself is not required — we stub the modules these tools import.

import importlib.util
import sys
import types

# ── Stub FreeCAD ─────────────────────────────────────────────────────
fc = types.ModuleType("FreeCAD")


class Vector:
    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = float(x), float(y), float(z)

    def __add__(self, o):
        return Vector(self.x + o.x, self.y + o.y, self.z + o.z)

    def __sub__(self, o):
        return Vector(self.x - o.x, self.y - o.y, self.z - o.z)

    def isEqual(self, o, tol):
        return abs(self.x - o.x) < tol and abs(self.y - o.y) < tol and abs(self.z - o.z) < tol


fc.Vector = Vector


class Rotation:
    def __init__(self, *args, **kwargs):
        pass


fc.Rotation = Rotation
sys.modules["FreeCAD"] = fc
sys.modules["Part"] = types.ModuleType("Part")
sys.modules["Sketcher"] = types.ModuleType("Sketcher")
sys.modules["Mesh"] = types.ModuleType("Mesh")

# ── Stub AICADAgent package imports ──────────────────────────────────
sys.modules["AICADAgent"] = types.ModuleType("AICADAgent")
sys.modules["AICADAgent.cad_tools"] = types.ModuleType("AICADAgent.cad_tools")

helpers = types.ModuleType("AICADAgent.cad_tools._helpers")
helpers.get_object = lambda doc, name: doc[name]
helpers.get_shape = lambda obj: obj.shape
helpers.analyze_topology = lambda shape: {}
sys.modules["AICADAgent.cad_tools._helpers"] = helpers

ds = types.ModuleType("AICADAgent.document_state")
ds._extract_object_state = lambda obj: {}
sys.modules["AICADAgent.document_state"] = ds

FREE = r"D:\project_main\NL-FreeCAD-Agent\freecad_addon\AICADAgent\cad_tools"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, f"{FREE}\\{filename}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


qt = load("qt_test", "query_tools.py")
sk = load("sk_test", "sketch_tools.py")

# ── Tests ────────────────────────────────────────────────────────────
results = []


def check(desc, cond):
    results.append((desc, cond))
    print(("PASS" if cond else "FAIL"), "-", desc)


class Box:
    def __init__(self, xmin, xmax, ymin, ymax, zmin, zmax):
        self.XMin, self.XMax = xmin, xmax
        self.YMin, self.YMax = ymin, ymax
        self.ZMin, self.ZMax = zmin, zmax
        self.XLength = xmax - xmin
        self.YLength = ymax - ymin
        self.ZLength = zmax - zmin
        self.Center = Vector((xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2)


class Obj:
    def __init__(self, name, type_id, bb):
        self.Name = name
        self.TypeId = type_id
        self._bb = bb

    def getBoundBox(self):
        return self._bb


# measure_gap: overlapping
doc = {"A": Obj("A", "Part::Box", Box(0, 10, 0, 10, 0, 10)),
       "B": Obj("B", "Part::Box", Box(5, 15, 0, 10, 0, 10))}
r = qt.measure_gap(doc, "A", "B", "X")
check("measure_gap overlap>0", r["query_result"]["overlap"] == 5.0)
check("measure_gap touching (overlap)", r["query_result"]["touching"] is True)

# measure_gap: separated
doc2 = {"A": Obj("A", "Part::Box", Box(0, 10, 0, 10, 0, 10)),
        "B": Obj("B", "Part::Box", Box(15, 25, 0, 10, 0, 10))}
r = qt.measure_gap(doc2, "A", "B", "X")
check("measure_gap gap=5", abs(r["query_result"]["gap"] - 5.0) < 1e-9)
check("measure_gap not touching", r["query_result"]["touching"] is False)

# compare_orientation: box 10x20x10, expected Z -> actual Y (dominant), fail
box_obj = Obj("Block", "Part::Box", Box(0, 10, 0, 20, 0, 10))
r = qt.compare_orientation({"Block": box_obj}, "Block", "Z")
check("box orientation: actual axis Y (dominant)", r["query_result"]["actual_axis"] == "Y")
check("box orientation: passed=False for Z", r["query_result"]["passed"] is False)
check("box orientation: not isotropic", r["query_result"]["isotropic"] is False)

r = qt.compare_orientation({"Block": box_obj}, "Block", "Y")
check("box orientation: passed=True for Y", r["query_result"]["passed"] is True)

# compare_orientation: cylinder vertical (2r x 2r x h, thin = X), expected X -> pass
cyl = Obj("Cylinder001", "Part::Cylinder", Box(0, 4, 0, 4, 0, 10))
r = qt.compare_orientation({"Cylinder001": cyl}, "Cylinder001", "X")
check("cylinder: thin axis X used", r["query_result"]["actual_axis"] == "X")
check("cylinder: passed=True", r["query_result"]["passed"] is True)

# compare_orientation: isotropic cube -> passed with note
cube = Obj("Cube", "Part::Box", Box(0, 10, 0, 10, 0, 10))
r = qt.compare_orientation({"Cube": cube}, "Cube", "Z")
check("cube: isotropic detected", r["query_result"]["isotropic"] is True)
check("cube: passed=True (indeterminate)", r["query_result"]["passed"] is True)
check("cube: note present", bool(r["query_result"]["note"]))

# _parse_face_index robustness
check("face index 'Face1' -> 0", sk._parse_face_index("Face1", 6) == 0)
check("face index 'face3' (lowercase) -> 2", sk._parse_face_index("face3", 6) == 2)
check("face index '4' -> 3", sk._parse_face_index("4", 6) == 3)
try:
    sk._parse_face_index("Face9", 6)
    check("face index out-of-range raises", False)
except ValueError:
    check("face index out-of-range raises", True)
try:
    sk._parse_face_index("abc", 6)
    check("face index garbage raises", False)
except ValueError:
    check("face index garbage raises", True)

failed = [d for d, c in results if not c]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
