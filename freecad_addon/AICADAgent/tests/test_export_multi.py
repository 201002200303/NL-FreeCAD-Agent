"""导出多目标 / 整文档 —— 运行在 FreeCAD 内:

    FreeCADCmd -c "exec(open(r'path/to/test_export_multi.py').read())"

验证「不 fuse 也能导出单一文件」：compound 与多目标导出必须真的能写出
STEP/STL，且属性（对象名、实体数）符合预期。这是替代整机 fuse 的关键前提。
"""
import os
import sys
import tempfile

ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ADDON_ROOT not in sys.path:
    sys.path.insert(0, os.path.dirname(ADDON_ROOT))

import FreeCAD
import Part
from AICADAgent.cad_tools import TOOL_REGISTRY

DOC = None


def _box(name, **kw):
    return TOOL_REGISTRY["create_box"](DOC, name=name, **kw)


def run_tests():
    global DOC
    DOC = FreeCAD.newDocument("ExportMulti")
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

    tmp = tempfile.mkdtemp(prefix="export_multi_")
    print("=" * 60)
    print("Export Multi-Target Tests")
    print("=" * 60)

    # 两个分离零件 + 一个组合体
    _box("Leg_L", length=20, width=30, height=112, pos_x=-40)
    _box("Torso", length=48, width=30, height=40, pos_z=112)
    TOOL_REGISTRY["make_compound"](DOC, name="Mecha", targets=["Leg_L", "Torso"])
    DOC.recompute()

    # 1) compound 保留源件
    check("compound_keeps_sources",
          DOC.getObject("Leg_L") is not None and DOC.getObject("Torso") is not None,
          "源零件被删除")

    # 2) 导出单个对象
    one = os.path.join(tmp, "torso.step")
    r = TOOL_REGISTRY["export_step"](DOC, target="Torso", filepath=one)
    check("export_single_step", os.path.exists(one) and os.path.getsize(one) > 0, r)
    check("export_single_reports_object", r.get("object") == "Torso", r)

    # 3) 导出多个对象（名称列表）
    multi = os.path.join(tmp, "two.step")
    r = TOOL_REGISTRY["export_step"](DOC, target=["Leg_L", "Torso"], filepath=multi)
    check("export_multi_step", os.path.exists(multi) and os.path.getsize(multi) > 0, r)
    check("export_multi_reports_objects", r.get("objects") == ["Leg_L", "Torso"], r)

    # 4) 导出整文档（target 省略）
    whole = os.path.join(tmp, "all.step")
    r = TOOL_REGISTRY["export_step"](DOC, filepath=whole)
    names = r.get("objects") or []
    check("export_whole_document", os.path.exists(whole) and os.path.getsize(whole) > 0, r)
    datum_types = {"App::Origin", "App::Line", "App::Plane", "App::Point"}
    exported_types = {DOC.getObject(n).TypeId for n in names}
    check("export_whole_skips_datums", not (exported_types & datum_types), exported_types)
    check("export_whole_includes_parts",
          {"Leg_L", "Torso", "Mecha"}.issubset(set(names)), names)

    # 5) STL 多目标
    stl = os.path.join(tmp, "two.stl")
    r = TOOL_REGISTRY["export_stl"](DOC, target=["Leg_L", "Torso"], filepath=stl)
    check("export_multi_stl", os.path.exists(stl) and os.path.getsize(stl) > 0, r)

    # 6) 缺失目标报可修复错误
    try:
        TOOL_REGISTRY["export_step"](DOC, target="Nope", filepath=os.path.join(tmp, "x.step"))
        check("export_missing_target_errors", False, "未抛异常")
    except ValueError as exc:
        check("export_missing_target_errors", "Nope" in str(exc), str(exc))

    # 7) STEP 回读：导出的多目标文件里确实是 2 个实体
    try:
        imported = FreeCAD.newDocument("ExportReadback")
        Part.insert(multi, imported.Name)
        imported.recompute()
        solids = sum(
            len(o.Shape.Solids) for o in imported.Objects if hasattr(o, "Shape") and o.Shape.Solids
        )
        check("step_readback_two_solids", solids == 2, f"solids={solids}")
        FreeCAD.closeDocument(imported.Name)
    except Exception as exc:  # noqa: BLE001
        check("step_readback_two_solids", False, f"{type(exc).__name__}: {exc}")

    # 8) 整文档导出排除被隐藏的源件：cut_hole 会隐藏原件，只留 Part::Cut 结果
    _box("HoleBase", length=40, width=40, height=10, pos_y=200)
    TOOL_REGISTRY["cut_hole"](DOC, target="HoleBase", hole_diameter=10, axis="Z")
    DOC.recompute()
    hole_obj = DOC.getObject("HoleBase_Hole")
    check("hole_hides_source",
          hole_obj is not None and not DOC.getObject("HoleBase").Visibility,
          "cut_hole 应隐藏原参数件")
    r = TOOL_REGISTRY["export_step"](DOC, filepath=os.path.join(tmp, "holes.step"))
    names_h = r.get("objects") or []
    check("whole_export_excludes_hidden_source", "HoleBase" not in names_h, names_h)
    check("whole_export_keeps_hole_result", "HoleBase_Hole" in names_h, names_h)

    FreeCAD.closeDocument(DOC.Name)
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.stdout.flush()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run_tests())
