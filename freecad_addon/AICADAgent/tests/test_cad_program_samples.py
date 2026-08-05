"""FreeCADCmd: 用真实 TOOL_REGISTRY 跑标准 cad 样例。

Run:
  D:\\freecad\\bin\\freecadcmd.exe -c "exec(open(r'D:\\project_main\\NL-FreeCAD-Agent\\freecad_addon\\AICADAgent\\tests\\test_cad_program_samples.py', encoding='utf-8').read())"
"""
from __future__ import print_function

import os
import sys
import traceback

ADDON_PARENT = r"D:\project_main\NL-FreeCAD-Agent\freecad_addon"
RESULT_LOG = r"D:\project_main\NL-FreeCAD-Agent\agent_service\data\_cad_program_samples_result.txt"
if ADDON_PARENT not in sys.path:
    sys.path.insert(0, ADDON_PARENT)

os.makedirs(os.path.dirname(RESULT_LOG), exist_ok=True)
_fh = open(RESULT_LOG, "w", encoding="utf-8")
_orig = sys.stdout


class _Tee(object):
    def write(self, data):
        try:
            _orig.write(data)
            _orig.flush()
        except Exception:
            pass
        try:
            _fh.write(data)
            _fh.flush()
        except Exception:
            pass

    def flush(self):
        try:
            _orig.flush()
        except Exception:
            pass
        try:
            _fh.flush()
        except Exception:
            pass


sys.stdout = _Tee()

import FreeCAD
from AICADAgent.cad_tools import TOOL_REGISTRY
from AICADAgent.cad_program import run_cad_program
from AICADAgent.executor import CadToolExecutor


SAMPLES = {
    "gear_keyway": """
root = cad.cylinder(name="Root", radius=24, height=10, center=(0, 0, 0))
tooth = cad.box(name="Tooth", size=(6, 6, 10), center=(27, 0, 0))
ring = cad.polar_pattern(tooth, count=12, angle=360, axis="Z", name_prefix="Tooth", fuse=True, fuse_name="ToothRing")
gear = cad.fuse(root, ring)
bore = cad.cylinder(name="Bore", radius=10, height=12, center=(0, 0, 0))
hollow = cad.cut(gear, bore)
key = cad.box(name="Keyway", size=(3.5, 6, 12), center=(11.75, 0, 0))
final = cad.cut(hollow, key)
""",
    "stepped_shaft": """
big = cad.cylinder(name="ShaftBig", radius=15, height=20, center=(0, 0, 10))
small = cad.cylinder(name="ShaftSmall", radius=10, height=40, center=(0, 0, 40))
shaft = cad.fuse(big, small)
""",
    "bracket": """
base = cad.box(name="Base", size=(40, 30, 5), center=(0, 0, 2.5))
wall = cad.box(name="Wall", size=(5, 30, 30), center=(-17.5, 0, 20))
bracket = cad.fuse(base, wall)
hole = cad.cylinder(name="Hole", radius=4, height=20, center=(0, 0, 2.5))
bracket = cad.cut(bracket, hole)
""",
    "symmetric_boxes": """
left = cad.box(name="Block_L", size=(10, 10, 10), center=(-20, 0, 5))
right = cad.box(name="Block_R", size=(10, 10, 10), center=(20, 0, 5))
""",
    "one_liner_gear": 'g=cad.cylinder(name="GearBody",radius=30,height=10,center=(0,0,0));b=cad.cylinder(name="Bore",radius=10,height=12,center=(0,0,0));h=cad.cut(g,b);k=cad.box(name="Keyway",size=(3.5,6,12),center=(11.75,0,0));f=cad.cut(h,k)',
    "linear_row": """
bar = cad.box(name="Bar", size=(5, 5, 5), center=(0, 0, 2.5))
row = cad.linear_pattern(bar, count=4, offset=(12, 0, 0), name_prefix="Bar", fuse=True, fuse_name="BarRow")
""",
}


def run_tests():
    passed = 0
    failed = 0
    print("=" * 60)
    print("CAD program standard samples (FreeCAD)")
    print("=" * 60)

    for name, code in SAMPLES.items():
        doc = FreeCAD.newDocument("CadSample_%s" % name)
        try:
            res = run_cad_program(code, doc=doc, registry=TOOL_REGISTRY, transaction="sample_%s" % name)
            if res.get("success"):
                passed += 1
                print("[PASS] run_cad_program %s -> %s" % (name, res.get("created")))
            else:
                failed += 1
                print("[FAIL] run_cad_program %s: %s" % (name, res))
        except Exception as e:
            failed += 1
            print("[FAIL] run_cad_program %s exception: %s" % (name, e))
            traceback.print_exc()
        finally:
            FreeCAD.closeDocument(doc.Name)

    # executor tool_call path
    doc = FreeCAD.newDocument("CadSample_Executor")
    try:
        ex = CadToolExecutor(doc)
        call = {
            "call_id": "t1",
            "tool": "execute_cad_program",
            "args": {"code": SAMPLES["gear_keyway"], "transaction": "via_executor"},
        }
        r = ex.execute_tool_call(call)
        if r.get("status") == "success":
            passed += 1
            print("[PASS] executor.execute_cad_program gear_keyway -> %s" % r.get("produced_objects"))
        else:
            failed += 1
            print("[FAIL] executor.execute_cad_program: %s" % r)
    except Exception as e:
        failed += 1
        print("[FAIL] executor exception: %s" % e)
        traceback.print_exc()
    finally:
        FreeCAD.closeDocument(doc.Name)

    print()
    print("=" * 60)
    print("Results: %d passed, %d failed" % (passed, failed))
    print("log: %s" % RESULT_LOG)
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = run_tests()
    if not ok:
        raise SystemExit(1)
