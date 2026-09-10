"""Full CAD tool smoke test — every TOOL_REGISTRY entry once.

Run (FreeCADCmd treats -c string as exec target on this install):
  D:\\freecad\\bin\\freecadcmd.exe -c "exec(open(r'D:\\project_main\\NL-FreeCAD-Agent\\freecad_addon\\AICADAgent\\tests\\test_all_tools_smoke.py', encoding='utf-8').read())"
"""
from __future__ import print_function

import os
import sys
import tempfile
import traceback

ADDON_PARENT = r"D:\project_main\NL-FreeCAD-Agent\freecad_addon"
RESULT_LOG = r"D:\project_main\NL-FreeCAD-Agent\agent_service\data\_tool_smoke_result.txt"
if ADDON_PARENT not in sys.path:
    sys.path.insert(0, ADDON_PARENT)

# Tee prints to file (FreeCADCmd stdout often lost under PowerShell)
os.makedirs(os.path.dirname(RESULT_LOG), exist_ok=True)
_result_fh = open(RESULT_LOG, "w", encoding="utf-8")
_orig_stdout = sys.stdout


class _Tee(object):
    def write(self, data):
        try:
            _orig_stdout.write(data)
            _orig_stdout.flush()
        except Exception:
            pass
        try:
            _result_fh.write(data)
            _result_fh.flush()
        except Exception:
            pass

    def flush(self):
        try:
            _orig_stdout.flush()
        except Exception:
            pass
        try:
            _result_fh.flush()
        except Exception:
            pass


sys.stdout = _Tee()

import FreeCAD
from AICADAgent.cad_tools import TOOL_REGISTRY
from AICADAgent.executor import CadToolExecutor


def _step(step_id, tool, args):
    return {"step_id": step_id, "tool": tool, "args": args, "depends_on": []}


def run_tests():
    doc = FreeCAD.newDocument("AllToolsSmoke")
    ex = CadToolExecutor(doc)
    passed = 0
    failed = 0
    results = []
    covered = set()

    def check(name, condition, detail="", tool=None):
        nonlocal passed, failed
        if tool:
            covered.add(tool)
        if condition:
            passed += 1
            print("[PASS] %s" % name)
            results.append((name, True, ""))
        else:
            failed += 1
            msg = str(detail)
            if len(msg) > 300:
                msg = msg[:300] + "..."
            print("[FAIL] %s: %s" % (name, msg))
            results.append((name, False, msg))

    def run(tool, args, expect_success=True, label=None):
        name = label or tool
        try:
            r = ex.execute_step(_step("t_%s_%d" % (tool, passed + failed), tool, args))
        except Exception as e:
            check(name, False, "exception: %s\n%s" % (e, traceback.format_exc()), tool=tool)
            return None
        ok = r.get("status") == "success"
        if expect_success:
            check(name, ok, r, tool=tool)
        else:
            check(name, not ok, r, tool=tool)
        return r

    print("=" * 60)
    print("All Tools Smoke Test (registry=%d)" % len(TOOL_REGISTRY))
    print("=" * 60)

    check("registry_count", len(TOOL_REGISTRY) >= 54, "got %d" % len(TOOL_REGISTRY))

    # ── primitives ──
    run("create_box", {"name": "BoxA", "length": 40, "width": 30, "height": 20})
    run("create_cylinder", {"name": "CylA", "radius": 8, "height": 25, "pos_x": 60})
    run("create_sphere", {"name": "SphA", "radius": 10, "pos_x": 100})
    run("create_cone", {
        "name": "ConeA", "radius1": 12, "radius2": 2, "height": 20, "pos_x": 140,
    })
    run("create_torus", {
        "name": "TorA", "radius1": 15, "radius2": 3, "pos_x": 180,
    })
    run("create_wedge", {
        "name": "WedgeA", "length": 30, "width": 20, "height": 15,
        "tip_scale": 0.4, "taper_axis": "Y", "pos_x": 220,
    })

    # ── boolean ──
    run("create_box", {"name": "B1", "length": 20, "width": 20, "height": 20, "pos_y": 80})
    run("create_box", {
        "name": "B2", "length": 20, "width": 20, "height": 20,
        "pos_x": 10, "pos_y": 80,
    })
    run("boolean_fuse", {"name": "Fused", "base": "B1", "tool": "B2"})
    run("create_box", {"name": "C1", "length": 20, "width": 20, "height": 20, "pos_y": 120})
    run("create_cylinder", {
        "name": "C2", "radius": 5, "height": 30, "pos_x": 10, "pos_y": 130,
    })
    run("boolean_cut", {"name": "CutOut", "base": "C1", "tool": "C2"})
    run("create_box", {"name": "K1", "length": 20, "width": 20, "height": 20, "pos_y": 160})
    run("create_box", {
        "name": "K2", "length": 20, "width": 20, "height": 20,
        "pos_x": 10, "pos_y": 160,
    })
    run("boolean_common", {"name": "CommonAB", "base": "K1", "tool": "K2"})

    # ── features ──
    run("create_box", {
        "name": "FeatBox", "length": 30, "width": 30, "height": 15, "pos_y": 220,
    })
    run("add_fillet", {
        "target": "FeatBox", "radius": 1.5, "edge_selector": "top",
        "result_name": "FeatFillet",
    })
    run("create_box", {
        "name": "ChamBox", "length": 30, "width": 30, "height": 15, "pos_y": 270,
    })
    run("add_chamfer", {
        "target": "ChamBox", "size": 1.5, "edge_selector": "top",
        "result_name": "FeatChamfer",
    })
    run("create_box", {
        "name": "HoleBox", "length": 30, "width": 30, "height": 15, "pos_y": 320,
    })
    run("cut_hole", {"target": "HoleBox", "hole_diameter": 6, "result_name": "HoleResult"})
    # mirror 已下线

    # ── transform / placement / modify ──
    run("set_placement", {
        "target": "CylA", "pos_x": 60, "pos_y": 0, "pos_z": 5,
        "rot_x": 0, "rot_y": 0, "rot_z": 15,
    })
    run("move", {"target": "ConeA", "dx": 5, "dy": 0, "dz": 0})
    run("rotate", {"target": "TorA", "axis": "Z", "angle": 30})
    run("scale", {
        "target": "SphA", "scale_x": 1.1, "scale_y": 1.1, "scale_z": 1.1,
        "result_name": "SphScaled",
    })
    run("copy_object", {"target": "BoxA", "name": "BoxCopy"})
    run("create_cylinder", {
        "name": "Peg", "radius": 2, "height": 8, "pos_x": 250, "pos_y": 0,
    })
    run("polar_pattern", {
        "target": "Peg", "count": 4, "angle": 360, "axis": "Z",
        "name_prefix": "Peg", "fuse": False,
    })
    run("create_box", {
        "name": "Bar1", "length": 5, "width": 5, "height": 5, "pos_x": 300,
    })
    run("linear_pattern", {
        "target": "Bar1", "count": 3, "dx": 10, "dy": 0, "dz": 0,
        "name_prefix": "Bar", "fuse": True, "fuse_name": "BarRow",
    })
    run("create_box", {
        "name": "RefBox", "length": 20, "width": 20, "height": 10, "pos_y": 400,
    })
    run("create_box", {
        "name": "MovBox", "length": 10, "width": 10, "height": 10,
        "pos_x": 50, "pos_y": 450,
    })
    run("align_objects", {
        "target": "MovBox", "reference": "RefBox", "axis": "z", "mode": "stack",
    })
    run("place_relative", {
        "target": "MovBox", "reference": "RefBox", "anchor": "top", "dz": 5,
    })
    run("create_box", {"name": "D1", "length": 5, "width": 5, "height": 5, "pos_y": 500})
    run("create_box", {"name": "D2", "length": 5, "width": 5, "height": 5, "pos_y": 500})
    run("create_box", {"name": "D3", "length": 5, "width": 5, "height": 5, "pos_y": 500})
    run("distribute_along", {"targets": "D1,D2,D3", "axis": "x", "spacing": 2})
    run("modify_param", {"target": "BoxA", "param": "Height", "value": 22})
    run("create_box", {
        "name": "ToDelete", "length": 5, "width": 5, "height": 5, "pos_y": 550,
    })
    run("delete_object", {"target": "ToDelete"})

    # ── query ──
    run("summarize_document", {})
    run("get_object_detail", {"target": "BoxA"})
    run("measure_gap", {"obj_a": "BoxA", "obj_b": "CylA", "axis": "X"})
    run("compare_orientation", {"target": "CylA", "expected_axis": "Z"})
    run("list_topology", {"target": "BoxA"})

    # ── sketch + partdesign ──
    run("create_body", {"name": "Body1"})
    run("create_sketch", {"name": "Sketch1", "plane": "XY", "body": "Body1"})
    run("sketch_add_line", {"sketch": "Sketch1", "x1": 0, "y1": 0, "x2": 20, "y2": 0})
    run("sketch_add_rect", {
        "sketch": "Sketch1", "x": 0, "y": 5, "width": 15, "height": 10,
    })
    run("sketch_add_circle", {
        "sketch": "Sketch1", "center_x": 30, "center_y": 10, "radius": 5,
    })
    run("sketch_add_arc", {
        "sketch": "Sketch1", "mode": "three_point",
        "x1": 40, "y1": 0, "x2": 45, "y2": 5, "x3": 40, "y3": 10,
    })
    run("sketch_add_polyline", {
        "sketch": "Sketch1",
        "points": [[50, 0], [55, 0], [55, 8], [50, 8]],
        "closed": True,
    })
    run("sketch_add_bspline", {
        "sketch": "Sketch1",
        "points": [[60, 0], [65, 5], [70, 0], [75, 5]],
        "mode": "interpolate",
    })
    # Fresh closed rect sketch for pad (skip redundant Horizontal on rect)
    run("create_sketch", {"name": "PadSketch", "plane": "XY", "body": "Body1"})
    run("sketch_add_rect", {
        "sketch": "PadSketch", "x": -10, "y": -10, "width": 20, "height": 20,
    })
    # Constraint smoke: Distance on a dedicated 2-point line sketch
    run("create_sketch", {"name": "ConstSketch", "plane": "XY", "body": "Body1"})
    run("sketch_add_line", {
        "sketch": "ConstSketch", "x1": 0, "y1": 0, "x2": 10, "y2": 0,
    })
    run("sketch_add_constraint", {
        "sketch": "ConstSketch", "constraint_type": "Horizontal",
        "geo1": 0, "point1": 1, "geo2": 0, "point2": 1,
    })
    run("pad_sketch", {
        "name": "Pad1", "sketch": "PadSketch", "length": 12, "body": "Body1",
    })

    # pocket on new sketch
    run("create_sketch", {"name": "PocketSketch", "plane": "XY", "body": "Body1"})
    run("sketch_add_circle", {
        "sketch": "PocketSketch", "center_x": 0, "center_y": 0, "radius": 3,
    })
    run("pocket_sketch", {
        "name": "Pocket1", "sketch": "PocketSketch", "length": 5, "body": "Body1",
    })

    # sketch on face + pad_to_face
    run("create_box", {
        "name": "FaceBox", "length": 25, "width": 25, "height": 15, "pos_x": 400,
    })
    run("create_body", {"name": "Body2"})
    r_face = run("create_sketch_on_face", {
        "name": "FaceSketch", "target": "FaceBox", "face": "Face6", "body": "Body2",
    })
    if r_face and r_face.get("status") == "success":
        run("sketch_add_circle", {
            "sketch": "FaceSketch", "center_x": 0, "center_y": 0, "radius": 4,
        })
        run("pad_to_face", {
            "name": "PadFace", "sketch": "FaceSketch", "target": "FaceBox",
            "face": "Face6", "length": 8, "body": "Body2",
        })
    else:
        check("pad_to_face", False, "skipped: create_sketch_on_face failed", tool="pad_to_face")

    # revolve
    run("create_body", {"name": "Body3"})
    run("create_sketch", {"name": "RevSketch", "plane": "XZ", "body": "Body3"})
    run("sketch_add_line", {"sketch": "RevSketch", "x1": 5, "y1": 0, "x2": 15, "y2": 0})
    run("sketch_add_line", {"sketch": "RevSketch", "x1": 15, "y1": 0, "x2": 15, "y2": 10})
    run("sketch_add_line", {"sketch": "RevSketch", "x1": 15, "y1": 10, "x2": 5, "y2": 10})
    run("sketch_add_line", {"sketch": "RevSketch", "x1": 5, "y1": 10, "x2": 5, "y2": 0})
    run("revolve_sketch", {
        "name": "Rev1", "sketch": "RevSketch", "axis_x": 0, "axis_y": 0, "axis_z": 1,
        "angle": 360, "body": "Body3",
    })

    # extrude_sketch (standalone)
    run("create_sketch", {"name": "ExtSketch", "plane": "XY"})
    run("sketch_add_circle", {
        "sketch": "ExtSketch", "center_x": 0, "center_y": 0, "radius": 6,
    })
    run("extrude_sketch", {
        "name": "Extrude1", "sketch": "ExtSketch", "length": 10,
        "direction_x": 0, "direction_y": 0, "direction_z": 1,
    })

    # ── surface ──
    run("create_sketch", {"name": "LoftA", "plane": "XY"})
    run("sketch_add_circle", {"sketch": "LoftA", "center_x": 0, "center_y": 0, "radius": 10})
    run("create_sketch", {"name": "LoftB", "plane": "XY", "pos_z": 30})
    run("sketch_add_circle", {"sketch": "LoftB", "center_x": 0, "center_y": 0, "radius": 5})
    run("make_loft", {"name": "Loft1", "profiles": ["LoftA", "LoftB"], "solid": True})

    run("create_sketch", {"name": "SweepProf", "plane": "XY"})
    run("sketch_add_circle", {
        "sketch": "SweepProf", "center_x": 0, "center_y": 0, "radius": 3,
    })
    run("create_sketch", {"name": "SweepPath", "plane": "XZ"})
    run("sketch_add_line", {
        "sketch": "SweepPath", "x1": 0, "y1": 0, "x2": 0, "y2": 40,
    })
    run("make_sweep", {
        "name": "Sweep1", "profile": "SweepProf", "path": "SweepPath",
        "make_solid": True,
    })

    run("create_sketch", {"name": "SurfRev", "plane": "XZ"})
    run("sketch_add_rect", {
        "sketch": "SurfRev", "x": 8, "y": 0, "width": 4, "height": 12,
    })
    run("make_revolve", {
        "name": "SurfRev1", "profile": "SurfRev",
        "axis_x": 0, "axis_y": 0, "axis_z": 1, "angle": 360,
    })

    # ── assembly ──
    run("create_assembly", {"name": "Asm1"})
    run("create_box", {
        "name": "PartA", "length": 20, "width": 20, "height": 10, "pos_x": 500,
    })
    run("create_box", {
        "name": "PartB", "length": 10, "width": 10, "height": 10,
        "pos_x": 540, "pos_y": 0, "pos_z": 20,
    })
    run("add_to_assembly", {"assembly": "Asm1", "part": "PartA"})
    run("add_to_assembly", {"assembly": "Asm1", "part": "PartB"})
    run("mate_planes", {
        "assembly": "Asm1", "part1": "PartA", "part2": "PartB",
        "plane1": "+Z", "plane2": "-Z",
    })
    run("create_cylinder", {
        "name": "Axle1", "radius": 3, "height": 30, "pos_x": 600,
    })
    run("create_cylinder", {
        "name": "Axle2", "radius": 3, "height": 20, "pos_x": 650, "pos_y": 20,
    })
    run("add_to_assembly", {"assembly": "Asm1", "part": "Axle1"})
    run("add_to_assembly", {"assembly": "Asm1", "part": "Axle2"})
    run("mate_coaxial", {
        "assembly": "Asm1", "part1": "Axle1", "part2": "Axle2", "axis": "Z",
    })

    # ── export ──
    tmp = tempfile.gettempdir()
    fcstd = os.path.join(tmp, "all_tools_smoke.FCStd")
    step_path = os.path.join(tmp, "all_tools_smoke.step")
    stl_path = os.path.join(tmp, "all_tools_smoke.stl")
    run("save_fcstd", {"filepath": fcstd})
    run("export_step", {"target": "BoxA", "filepath": step_path})
    run("export_stl", {"target": "BoxA", "filepath": stl_path})
    check("export_step_file_exists", os.path.exists(step_path), step_path)
    check("export_stl_file_exists", os.path.exists(stl_path), stl_path)

    # Coverage: every registry tool must have been invoked
    missing = sorted(set(TOOL_REGISTRY.keys()) - covered)
    check("all_registry_tools_invoked", not missing, "missing: %s" % missing)

    print()
    print("=" * 60)
    print("Results: %d passed, %d failed" % (passed, failed))
    if failed:
        print("Failed:")
        for name, ok, detail in results:
            if not ok:
                print("  - %s: %s" % (name, detail))
    print("=" * 60)
    FreeCAD.closeDocument(doc.Name)
    return failed == 0


if __name__ == "__main__":
    ok = run_tests()
    if not ok:
        raise SystemExit(1)
