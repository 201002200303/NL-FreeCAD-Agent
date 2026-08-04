"""V0.6 FreeCAD functional tests — run inside FreeCAD:

    FreeCADCmd -c "exec(open(r'path/to/test_v06_freecad_tools.py').read())"

Or from FreeCAD Python console after loading the addon path.
"""
import sys
import os
import tempfile

# Ensure addon is importable
ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ADDON_ROOT not in sys.path:
    sys.path.insert(0, os.path.dirname(ADDON_ROOT))

import FreeCAD
from AICADAgent.cad_tools import TOOL_REGISTRY
from AICADAgent.executor import CadToolExecutor


def _step(step_id, tool, args):
    return {"step_id": step_id, "tool": tool, "args": args, "depends_on": []}


def run_tests():
    doc = FreeCAD.newDocument("V06_Test")
    ex = CadToolExecutor(doc)
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            failed += 1
            print(f"  [FAIL] {name}: {detail}")

    print("=" * 50)
    print("V0.6 FreeCAD Tool Functional Tests")
    print("=" * 50)

    # Primitives
    r = ex.execute_step(_step("s1", "create_sphere", {"name": "Ball", "radius": 10}))
    check("create_sphere", r.get("status") == "success", r)

    r = ex.execute_step(_step("s2", "create_cone", {
        "name": "Cone1", "radius1": 10, "radius2": 0, "height": 20,
    }))
    check("create_cone", r.get("status") == "success", r)

    r = ex.execute_step(_step("s3", "create_torus", {
        "name": "Ring", "radius1": 20, "radius2": 3,
    }))
    check("create_torus", r.get("status") == "success", r)

    r = ex.execute_step(_step("s4", "create_box", {
        "name": "Base", "length": 50, "width": 50, "height": 5,
    }))
    check("create_box", r.get("status") == "success", r)

    r = ex.execute_step(_step("s5", "create_cylinder", {
        "name": "Pole", "radius": 3, "height": 40, "pos_z": 5,
    }))
    check("create_cylinder", r.get("status") == "success", r)

    # Transform
    r = ex.execute_step(_step("s6", "move", {"target": "Pole", "dx": 0, "dy": 0, "dz": 0}))
    check("move", r.get("status") == "success", r)

    r = ex.execute_step(_step("s7", "copy_object", {"target": "Ball", "name": "BallCopy"}))
    check("copy_object", r.get("status") == "success", r)

    # Boolean
    r = ex.execute_step(_step("s8", "boolean_fuse", {
        "name": "LampBase", "base": "Base", "tool": "Pole",
    }))
    check("boolean_fuse", r.get("status") == "success", r)

    # Features
    r = ex.execute_step(_step("s9", "add_fillet", {
        "target": "Base", "radius": 1, "edge_selector": "top",
    }))
    check("add_fillet", r.get("status") == "success", r)

    r = ex.execute_step(_step("s10", "cut_hole", {
        "target": "Base", "hole_diameter": 5,
    }))
    check("cut_hole", r.get("status") == "success", r)

    # mirror 已从 TOOL_REGISTRY 移除；对称改对侧 create
    r = ex.execute_step(_step("s11", "copy_object", {
        "target": "Ball", "name": "BallCopy",
    }))
    check("copy_object", r.get("status") == "success", r)

    # Export
    tmp = tempfile.gettempdir()
    step_path = os.path.join(tmp, "v06_test.step")
    stl_path = os.path.join(tmp, "v06_test.stl")

    r = ex.execute_step(_step("s12", "export_step", {
        "target": "Base", "filepath": step_path,
    }))
    check("export_step", r.get("status") == "success" and os.path.exists(step_path), r)

    r = ex.execute_step(_step("s13", "export_stl", {
        "target": "Ball", "filepath": stl_path,
    }))
    check("export_stl", r.get("status") == "success" and os.path.exists(stl_path), r)

    # Registry completeness
    check("registry_count", len(TOOL_REGISTRY) == 54, f"got {len(TOOL_REGISTRY)}")

    print()
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50)
    FreeCAD.closeDocument(doc.Name)
    return failed == 0


if __name__ == "__main__":
    ok = run_tests()
    if not ok:
        raise SystemExit(1)
