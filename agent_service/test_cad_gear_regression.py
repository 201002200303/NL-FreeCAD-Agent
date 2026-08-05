"""回归：齿轮式 code（list.append + size/center）须能通过校验并映射执行。"""

from app.cad_program.runtime import run_cad_program
from app.cad_program.validate import validate_cad_source
from app.schemas.session import ToolCall
from app.workflow.chat import prefilter_tool_calls


GEAR_CODE = """
gear_body = cad.cylinder(name="GearBody", radius=25, height=15, center=(0,0,7.5))
teeth = []
for i in range(8):
    angle_deg = i * 45
    tooth = cad.box(name=f"Tooth_{i}", size=(10,6,15), center=(30,0,7.5))
    tooth = cad.rotate(tooth, axis=(0,0,1), angle=angle_deg, pivot=(0,0,0))
    teeth.append(tooth)
gear_with_teeth = gear_body
for t in teeth:
    gear_with_teeth = cad.fuse(gear_with_teeth, t)
shaft_hole = cad.cylinder(name="ShaftHole", radius=10, height=20, center=(0,0,7.5))
gear_final = cad.cut(gear_with_teeth, shaft_hole)
keyway = cad.box(name="Keyway", size=(3.5,6,15), center=(11.75,0,7.5))
gear_final = cad.cut(gear_final, keyway)
"""


def test_gear_style_code_passes_validation():
    verdict = validate_cad_source(GEAR_CODE)
    assert verdict.ok is True, verdict.violations


def test_list_append_allowed_but_dunder_still_forbidden():
    assert validate_cad_source("xs=[]\nxs.append(1)").ok is True
    assert validate_cad_source("x = cad.__dict__").ok is False


def test_prefilter_keeps_code_and_blocked_fields():
    bad = 'import os\nx = cad.box(name="X", size=(1,1,1), center=(0,0,0))'
    calls = [{"tool": "execute_cad_program", "args": {"code": bad}, "description": "x"}]
    out = prefilter_tool_calls(calls)[0]
    assert out["blocked"] is True
    assert out["preflight_error"]
    assert out["args"]["code"] == bad  # 保留原文供模型对照
    # 必须能过 ToolCall schema（不被剥掉）
    tc = ToolCall(
        call_id="chat_1",
        tool=out["tool"],
        args=out["args"],
        description=out.get("description") or "",
        blocked=out.get("blocked"),
        preflight_error=out.get("preflight_error"),
    )
    assert tc.blocked is True
    assert tc.args["code"] == bad


def test_runtime_maps_size_center_and_positional_boolean():
    calls = []

    def fake_box(doc, name="Box", length=10, width=10, height=10, pos_x=0, pos_y=0, pos_z=0, anchor="min", **kw):
        calls.append(("box", dict(name=name, length=length, width=width, height=height,
                                  pos_x=pos_x, pos_y=pos_y, pos_z=pos_z, anchor=anchor)))
        return {"object": name}

    def fake_cyl(doc, name="C", radius=1, height=1, pos_x=0, pos_y=0, pos_z=0, **kw):
        calls.append(("cyl", dict(name=name, radius=radius, height=height, pos_x=pos_x, pos_y=pos_y, pos_z=pos_z)))
        return {"object": name}

    def fake_rotate(doc, target="", axis="Z", angle=0, origin_x=0, origin_y=0, origin_z=0, **kw):
        calls.append(("rotate", dict(target=target, axis=axis, angle=angle,
                                     origin_x=origin_x, origin_y=origin_y, origin_z=origin_z)))
        return {"object": target}

    def fake_fuse(doc, name="Fuse", base="", tool=""):
        calls.append(("fuse", dict(name=name, base=base, tool=tool)))
        return {"object": name}

    def fake_cut(doc, name="Cut", base="", tool=""):
        calls.append(("cut", dict(name=name, base=base, tool=tool)))
        return {"object": name}

    registry = {
        "create_box": fake_box,
        "create_cylinder": fake_cyl,
        "rotate": fake_rotate,
        "boolean_fuse": fake_fuse,
        "boolean_cut": fake_cut,
    }
    res = run_cad_program(GEAR_CODE, doc=object(), registry=registry)
    assert res["success"] is True, res
    box_calls = [c for c in calls if c[0] == "box"]
    assert box_calls[0][1]["anchor"] == "center"
    assert box_calls[0][1]["length"] == 10
    fuse_calls = [c for c in calls if c[0] == "fuse"]
    assert len(fuse_calls) == 8
    assert fuse_calls[0][1]["base"] == "GearBody"
    rot = [c for c in calls if c[0] == "rotate"][0][1]
    assert rot["axis"] == "Z"
    assert rot["target"] == "Tooth_0"
