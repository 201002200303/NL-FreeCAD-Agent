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
    print("PASS linear_pattern fuse")
    print("ALL PASS")
    return True


if __name__ == "__main__":
    run()
