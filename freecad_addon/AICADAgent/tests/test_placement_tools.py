# test_placement_tools.py — FreeCAD-side smoke test for relative placement
# Run inside FreeCAD Python console / Macro.

import FreeCAD
import Part


def run():
    doc = FreeCAD.newDocument("PlacementToolsTest")
    from AICADAgent.cad_tools.placement_tools import (
        align_objects,
        place_relative,
        distribute_along,
    )

    box_a = doc.addObject("Part::Box", "RefBox")
    box_a.Length = 20
    box_a.Width = 20
    box_a.Height = 10
    box_b = doc.addObject("Part::Box", "MovBox")
    box_b.Length = 10
    box_b.Width = 10
    box_b.Height = 10
    box_b.Placement.Base = FreeCAD.Vector(50, 50, 50)
    doc.recompute()

    align_objects(doc, target="MovBox", reference="RefBox", axis="z", mode="stack")
    doc.recompute()
    bb_r = box_a.Shape.BoundBox
    bb_t = box_b.Shape.BoundBox
    assert abs(bb_t.ZMin - bb_r.ZMax) < 1e-6, (bb_t.ZMin, bb_r.ZMax)
    print("PASS align_objects stack")

    place_relative(doc, target="MovBox", reference="RefBox", anchor="top", dz=5)
    doc.recompute()
    bb_t = box_b.Shape.BoundBox
    expected_z = bb_r.ZMax + 5
    assert abs(bb_t.Center.z - expected_z) < 1e-5, (bb_t.Center.z, expected_z)
    print("PASS place_relative top+dz")

    c1 = doc.addObject("Part::Box", "D1")
    c1.Length = c1.Width = c1.Height = 5
    c2 = doc.addObject("Part::Box", "D2")
    c2.Length = c2.Width = c2.Height = 5
    c2.Placement.Base = FreeCAD.Vector(0, 0, 0)
    c3 = doc.addObject("Part::Box", "D3")
    c3.Length = c3.Width = c3.Height = 5
    doc.recompute()
    distribute_along(doc, targets="D1,D2,D3", axis="x", spacing=2)
    doc.recompute()
    gap12 = c2.Shape.BoundBox.XMin - c1.Shape.BoundBox.XMax
    gap23 = c3.Shape.BoundBox.XMin - c2.Shape.BoundBox.XMax
    assert abs(gap12 - 2) < 1e-5 and abs(gap23 - 2) < 1e-5, (gap12, gap23)
    print("PASS distribute_along")
    print("ALL PASS")
    return True


if __name__ == "__main__":
    run()
