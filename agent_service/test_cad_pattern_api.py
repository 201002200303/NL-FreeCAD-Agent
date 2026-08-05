"""阵列语法：圆周/直线均布必须走 polar/linear_pattern，不靠 rotate 循环。"""

from app.cad_program.runtime import run_cad_program
from app.cad_program.validate import validate_cad_source

GEAR_VIA_POLAR = """
root = cad.cylinder(name="Root", radius=24, height=10, center=(0, 0, 0))
tooth = cad.box(name="Tooth", size=(6, 6, 10), center=(27, 0, 0))
ring = cad.polar_pattern(
    tooth, count=12, angle=360, axis="Z",
    name_prefix="Tooth", fuse=True, fuse_name="ToothRing",
)
gear = cad.fuse(root, ring)
bore = cad.cylinder(name="Bore", radius=10, height=12, center=(0, 0, 0))
hollow = cad.cut(gear, bore)
key = cad.box(name="Keyway", size=(3.5, 6, 12), center=(11.75, 0, 0))
final = cad.cut(hollow, key)
"""

LINEAR_VIA_PATTERN = """
bar = cad.box(name="Bar", size=(5, 5, 5), center=(0, 0, 2.5))
row = cad.linear_pattern(bar, count=4, offset=(12, 0, 0), name_prefix="Bar", fuse=True, fuse_name="BarRow")
"""


def test_gear_polar_pattern_validates():
    assert validate_cad_source(GEAR_VIA_POLAR).ok is True


def test_polar_and_linear_map_to_registry_kwargs():
    calls = []

    def fake_cyl(doc, **kw):
        calls.append(("cyl", kw))
        return {"object": kw.get("name", "C")}

    def fake_box(doc, **kw):
        calls.append(("box", kw))
        return {"object": kw.get("name", "B")}

    def fake_polar(doc, target="", count=4, angle=360, axis="Z", name_prefix="", fuse=False, fuse_name="", origin_x=0, origin_y=0, origin_z=0, **kw):
        calls.append(("polar", dict(target=target, count=count, angle=angle, axis=axis,
                                    name_prefix=name_prefix, fuse=fuse, fuse_name=fuse_name,
                                    origin_x=origin_x, origin_y=origin_y, origin_z=origin_z)))
        return {"object": fuse_name or target, "created": [f"{name_prefix}{i}" for i in range(2, int(count) + 1)]}

    def fake_linear(doc, target="", count=2, dx=10, dy=0, dz=0, name_prefix="", fuse=False, fuse_name="", **kw):
        calls.append(("linear", dict(target=target, count=count, dx=dx, dy=dy, dz=dz,
                                     name_prefix=name_prefix, fuse=fuse, fuse_name=fuse_name)))
        return {"object": fuse_name or target, "created": []}

    def fake_fuse(doc, name="Fuse", base="", tool=""):
        calls.append(("fuse", dict(name=name, base=base, tool=tool)))
        return {"object": name}

    def fake_cut(doc, name="Cut", base="", tool=""):
        calls.append(("cut", dict(name=name, base=base, tool=tool)))
        return {"object": name}

    registry = {
        "create_cylinder": fake_cyl,
        "create_box": fake_box,
        "polar_pattern": fake_polar,
        "linear_pattern": fake_linear,
        "boolean_fuse": fake_fuse,
        "boolean_cut": fake_cut,
    }

    res = run_cad_program(GEAR_VIA_POLAR, doc=object(), registry=registry)
    assert res["success"] is True, res
    polar = [c for c in calls if c[0] == "polar"][0][1]
    assert polar["target"] == "Tooth"
    assert polar["count"] == 12
    assert polar["fuse"] is True
    assert polar["fuse_name"] == "ToothRing"

    calls.clear()
    res2 = run_cad_program(LINEAR_VIA_PATTERN, doc=object(), registry=registry)
    assert res2["success"] is True, res2
    lin = [c for c in calls if c[0] == "linear"][0][1]
    assert lin["target"] == "Bar"
    assert lin["count"] == 4
    assert lin["dx"] == 12
    assert lin["fuse_name"] == "BarRow"
