# test_pattern_tools.py — copy_object / polar_pattern / linear_pattern smoke test
# Run inside FreeCAD Python console / Macro.

import FreeCAD
import Part


def run():
    doc = FreeCAD.newDocument("PatternToolsTest")
    from AICADAgent.cad_tools.transform_tools import (
        copy_object,
        polar_pattern,
        linear_pattern,
    )

    box = doc.addObject("Part::Box", "Tooth1")
    box.Length = 6
    box.Width = 10
    box.Height = 20
    box.Placement.Base = FreeCAD.Vector(-3, 40, 0)
    doc.recompute()

    r = copy_object(doc, target="Tooth1", name="Tooth2")
    doc.recompute()
    assert r["object"] == "Tooth2", r
    assert doc.getObject("Tooth2") is not None
    print("PASS copy_object named result")

    # copy_object must NOT pass name as copyObject's 3rd (bool) arg — already validated by success
    cyl = doc.addObject("Part::Cylinder", "Peg")
    cyl.Radius = 2
    cyl.Height = 8
    cyl.Placement.Base = FreeCAD.Vector(30, 0, 0)
    doc.recompute()

    pr = polar_pattern(
        doc,
        target="Peg",
        count=4,
        angle=360,
        axis="Z",
        name_prefix="Peg",
        fuse=False,
    )
    doc.recompute()
    assert len(pr["created"]) == 3, pr
    for name in ("Peg2", "Peg3", "Peg4"):
        assert doc.getObject(name) is not None, name
    print("PASS polar_pattern 4 instances")

    bar = doc.addObject("Part::Box", "Bar1")
    bar.Length = bar.Width = bar.Height = 5
    doc.recompute()
    lr = linear_pattern(
        doc,
        target="Bar1",
        count=3,
        dx=10,
        dy=0,
        dz=0,
        name_prefix="Bar",
        fuse=True,
        fuse_name="BarRow",
    )
    doc.recompute()
    assert lr.get("fused") == "BarRow", lr
    assert doc.getObject("BarRow") is not None
    # fuse 后源件必须删掉，不能只隐藏
    assert doc.getObject("Bar1") is None, "source Bar1 should be removed after fuse"
    assert doc.getObject("Bar2") is None, "source Bar2 should be removed after fuse"
    assert doc.getObject("Bar3") is None, "source Bar3 should be removed after fuse"
    print("PASS linear_pattern fuse")

    # ── Placement 坑回归：move 之后再 pattern(fuse)，装配体必须跟随新位姿 ──
    # 旧实现 fuse 用裸 obj.Shape；Part::Feature 位移只在 Placement → 装配体落在原点。
    blade = doc.addObject("Part::Box", "BladeT")
    blade.Length, blade.Width, blade.Height = 10, 4, 2
    doc.recompute()

    from AICADAgent.cad_tools.transform_tools import move, rotate

    move(doc, target="BladeT", dx=70.71, dy=70.71, dz=27)
    doc.recompute()
    pr2 = polar_pattern(
        doc,
        target="BladeT",
        count=2,
        angle=360,
        axis="Z",
        origin_x=70.71,
        origin_y=70.71,
        origin_z=27,
        name_prefix="BladeT",
        fuse=True,
        fuse_name="PropAsmT",
    )
    doc.recompute()
    asm = doc.getObject("PropAsmT")
    assert asm is not None, pr2
    bb = asm.Shape.BoundBox
    # 原叶在 (70.71,70.71,27)，复制叶绕电机转 180° 到对称侧 → bbox 对称包围电机位
    # 即：bbox 中心应贴近电机 (70.71, 70.71)，z 范围贴合叶厚（27~29 不叠 z 平移）
    assert abs(bb.Center.x - 70.71) < 2, bb
    assert abs(bb.Center.y - 70.71) < 2, bb
    assert 25 < bb.ZMin < 29, bb
    assert 27 < bb.ZMax < 31, bb
    assert bb.Center.Length > 80, bb
    # 幽灵扇叶回归：fuse 后原件/副本必须消失
    assert doc.getObject("BladeT") is None, "BladeT must be removed after fuse"
    assert doc.getObject("BladeT2") is None, "BladeT2 must be removed after fuse"
    print("PASS polar_pattern fuse honors Placement")

    # rotate 之后再 fuse：转到 45° 的盒子与未转盒子合并，bbox 必须包含两者
    b1 = doc.addObject("Part::Box", "FuseA")
    b1.Length = b1.Width = b1.Height = 10
    b2 = doc.addObject("Part::Box", "FuseB")
    b2.Length = b2.Width = b2.Height = 10
    doc.recompute()
    rotate(doc, target="FuseB", axis="Z", angle=45, origin_x=0, origin_y=0, origin_z=0)
    from AICADAgent.cad_tools.boolean_tools import boolean_fuse
    bf = boolean_fuse(doc, name="FuseAsm", base="FuseA", tool="FuseB")
    doc.recompute()
    fa = doc.getObject("FuseAsm")
    assert fa is not None and not fa.Shape.isNull(), bf
    # 45° 旋转后 10×10 截面外接半径 ~7.07，合并 bbox 边长应明显大于 10
    assert fa.Shape.BoundBox.XLength > 12, fa.Shape.BoundBox
    print("PASS boolean_fuse world shape")
    print("ALL PASS")
    return True


if __name__ == "__main__":
    run()
