"""execute_cad_program 客户端运行时：把 code 映射到现有 TOOL_REGISTRY，单事务执行。"""

from app.cad_program.runtime import run_cad_program


def test_box_and_cut_run_in_single_transaction():
    calls: list[tuple[str, dict]] = []

    def fake_create_box(doc, name="Box", length=10, width=10, height=10, **kw):
        calls.append(("create_box", {"name": name}))
        return {"object": name, "type": "Part::Box"}

    def fake_create_cylinder(doc, name="Cyl", radius=5, height=10, **kw):
        calls.append(("create_cylinder", {"name": name}))
        return {"object": name, "type": "Part::Cylinder"}

    def fake_boolean_cut(doc, name="Cut", base="", tool=""):
        calls.append(("boolean_cut", {"name": name, "base": base, "tool": tool}))
        return {"object": name, "type": "Part::Cut"}

    registry = {
        "create_box": fake_create_box,
        "create_cylinder": fake_create_cylinder,
        "boolean_cut": fake_boolean_cut,
    }

    code = """
base = cad.box(name="Base", size=(40, 25, 10), center=(0, 0, 5))
hole = cad.cylinder(name="HoleTool", radius=5, height=20, center=(0, 0, 5))
result = cad.cut(name="Bracket", base=base, tool=hole)
"""
    res = run_cad_program(code, doc=object(), registry=registry)

    assert res["success"] is True
    names = [c[1]["name"] for c in calls]
    assert names == ["Base", "HoleTool", "Bracket"]
    assert res["created"] == ["Base", "HoleTool", "Bracket"]
    assert res["transaction"] is not None


def test_failure_aborts_transaction_and_reports_line():
    def boom(doc, **kw):
        raise RuntimeError("boolean failed")

    registry = {
        "create_box": lambda doc, **kw: {"object": kw.get("name", "B")},
        "boolean_cut": boom,
    }
    code = 'b = cad.box(name="B", size=(1,1,1), center=(0,0,0))\ncad.cut(name="C", base=b, tool="nope")'
    res = run_cad_program(code, doc=object(), registry=registry)

    assert res["success"] is False
    assert res["error_type"] in ("tool_error", "boolean_error", "runtime_error")
    assert res.get("failed_line")
    assert "boolean failed" in (res.get("error_message") or "")


def test_same_name_create_deletes_existing_first():
    """同名再创建时先删再建，避免 FreeCAD 自动改名成 Name001。"""
    objects: dict[str, object] = {}
    calls: list[tuple[str, str]] = []

    class Doc:
        def getObject(self, name):
            return objects.get(name)

    def fake_create_box(doc, name="Box", **kw):
        # 模拟 FreeCAD：若未删干净则改名
        final = name
        if name in objects:
            final = f"{name}001"
        objects[final] = object()
        calls.append(("create", final))
        return {"object": final}

    def fake_delete(doc, target=""):
        calls.append(("delete", target))
        objects.pop(target, None)
        return {"object": target, "deleted": True}

    registry = {"create_box": fake_create_box, "delete_object": fake_delete}
    doc = Doc()
    code = (
        'a = cad.box(name="Backpack", size=(10,10,10), center=(0,0,0))\n'
        'b = cad.box(name="Backpack", size=(12,12,12), center=(0,0,1))\n'
    )
    res = run_cad_program(code, doc=doc, registry=registry)
    assert res["success"] is True
    assert ("delete", "Backpack") in calls
    assert res["created"] == ["Backpack", "Backpack"]
    assert "Backpack001" not in objects
    assert "Backpack" in objects


def test_soft_delete_missing_and_list():
    objects = {"Keep": object(), "Gone": object()}

    class Doc:
        def getObject(self, name):
            return objects.get(name)

    def fake_delete(doc, target=""):
        if target not in objects:
            raise ValueError(f"Object not found: {target}")
        objects.pop(target)
        return {"object": target, "deleted": True}

    registry = {"delete_object": fake_delete, "create_box": lambda doc, **kw: {"object": kw.get("name")}}
    code = 'cad.delete(["Gone", "Missing"])\ncad.delete("AlsoMissing")\n'
    res = run_cad_program(code, doc=Doc(), registry=registry)
    assert res["success"] is True
    assert "Gone" not in objects
    assert "Keep" in objects


def test_rejects_code_that_fails_server_validation():
    res = run_cad_program("import os", doc=object(), registry={})
    assert res["success"] is False
    assert res["error_type"] in ("validation_error", "syntax_error", "forbidden")


def test_math_namespace_supports_attribute_calls():
    seen = {}

    def fake_box(doc, name="Box", **kwargs):
        seen["name"] = name
        return {"object": name}

    res = run_cad_program(
        'x = cad.box(name=f"B{round(math.sin(math.pi / 2))}", size=(1,1,1), center=(0,0,0))',
        doc=object(),
        registry={"create_box": fake_box},
    )
    assert res["success"] is True, res
    assert seen["name"] == "B1"


def test_runtime_rejects_large_loop_expansion():
    res = run_cad_program(
        'for i in range(100000000):\n    pass',
        doc=object(),
        registry={},
    )
    assert res["success"] is False
    assert "range expands" in res["error_message"]



def test_sketch_polyline_extrude_mapping():
    calls: list[tuple[str, dict]] = []

    def fake_sketch(doc, name="Sketch", plane="XY", **kw):
        calls.append(("create_sketch", {"name": name, "plane": plane}))
        return {"object": name}

    def fake_polyline(doc, sketch="", points=None, closed=False, **kw):
        calls.append(("sketch_add_polyline", {"sketch": sketch, "points": points, "closed": closed}))
        return {"tool": "sketch_add_polyline", "sketch": sketch, "closed": closed}

    def fake_extrude(doc, name="Extrude", sketch="", length=10, direction_x=0, direction_y=0, direction_z=1, **kw):
        calls.append(("extrude_sketch", {
            "name": name, "sketch": sketch, "length": length,
            "direction": (direction_x, direction_y, direction_z),
        }))
        return {"object": name}

    registry = {
        "create_sketch": fake_sketch,
        "sketch_add_polyline": fake_polyline,
        "extrude_sketch": fake_extrude,
        "delete_object": lambda doc, target="": {"object": target},
    }
    code = """
sk = cad.sketch(name="Profile", plane="XZ")
cad.polyline(sk, points=[[0,0],[100,0],[100,40],[0,40]], closed=True)
body = cad.extrude(name="Main", sketch=sk, length=50, direction=(1,0,0))
"""
    res = run_cad_program(code, doc=object(), registry=registry)
    assert res["success"] is True, res
    assert calls[0] == ("create_sketch", {"name": "Profile", "plane": "XZ"})
    assert calls[1][0] == "sketch_add_polyline"
    assert calls[1][1]["sketch"] == "Profile"
    assert calls[1][1]["closed"] is True
    assert calls[2] == ("extrude_sketch", {
        "name": "Main", "sketch": "Profile", "length": 50, "direction": (1.0, 0.0, 0.0),
    })
    assert res["created"] == ["Profile", "Main"]


def test_line_rect_circle_positional_and_rotate_center():
    calls: list[tuple[str, dict]] = []

    def fake_line(doc, sketch="", x1=0, y1=0, x2=10, y2=0, **kw):
        calls.append(("line", {"sketch": sketch, "x1": x1, "y1": y1, "x2": x2, "y2": y2}))
        return {}

    def fake_rect(doc, sketch="", x=0, y=0, width=10, height=10, **kw):
        calls.append(("rect", {"sketch": sketch, "x": x, "y": y, "width": width, "height": height}))
        return {}

    def fake_circle(doc, sketch="", center_x=0, center_y=0, radius=5, **kw):
        calls.append(("circle", {"sketch": sketch, "cx": center_x, "cy": center_y, "r": radius}))
        return {}

    def fake_rotate(doc, target="", axis="Z", angle=0, origin_x=0, origin_y=0, origin_z=0, **kw):
        calls.append(("rotate", {
            "target": target, "axis": axis, "angle": angle,
            "origin": (origin_x, origin_y, origin_z),
        }))
        return {"object": target}

    def fake_extrude(doc, name="E", sketch="", length=10, **kw):
        assert "center" not in kw
        calls.append(("extrude", {"name": name, "sketch": sketch}))
        return {"object": name}

    registry = {
        "create_sketch": lambda doc, name="S", **kw: {"object": name},
        "sketch_add_line": fake_line,
        "sketch_add_rect": fake_rect,
        "sketch_add_circle": fake_circle,
        "rotate": fake_rotate,
        "extrude_sketch": fake_extrude,
        "delete_object": lambda doc, target="": {"object": target},
    }
    code = """
sk = cad.sketch(name="S", plane="XY")
cad.line(sk, -10, 0, 10, 0)
cad.rect(sk, center=(0, 5), width=20, height=10)
cad.circle(sk, 0, 0, 4)
cad.rotate("S", axis="X", angle=-15, center=(1, 2, 3))
cad.extrude(name="E", sketch=sk, length=5, direction=(0, 0, 1), center=(0, 0, 0))
"""
    res = run_cad_program(code, doc=object(), registry=registry)
    assert res["success"] is True, res
    assert ("line", {"sketch": "S", "x1": -10.0, "y1": 0.0, "x2": 10.0, "y2": 0.0}) in calls
    assert ("rect", {"sketch": "S", "x": -10.0, "y": 0.0, "width": 20.0, "height": 10.0}) in calls
    assert ("circle", {"sketch": "S", "cx": 0.0, "cy": 0.0, "r": 4.0}) in calls
    assert ("rotate", {"target": "S", "axis": "X", "angle": -15, "origin": (1.0, 2.0, 3.0)}) in calls
    assert ("extrude", {"name": "E", "sketch": "S"}) in calls


def test_cylinder_center_accounts_for_rotation():
    """侧向圆柱：center 必须是旋转后的几何中心，不能只在世界 Z 减半高。"""
    from app.cad_program.runtime import (
        _axis_body_base_from_center,
        _normalize_cad_args,
        _rotate_fixed_axes,
    )

    def _close(a, b, tol=1e-9):
        assert all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b)), (a, b)

    # 无旋转：仍退化为 pos_z = cz - h/2
    _close(_axis_body_base_from_center((0, 0, 5), 20), (0.0, 0.0, -5.0))

    # rot_y=90：局部 (0,0,5) → 世界 (+5,0,0)；Base = center - offset
    base = _axis_body_base_from_center((-24, 0, 70), 10, rot_y=90)
    _close(base, (-29.0, 0.0, 70.0))
    mid = _rotate_fixed_axes(0, 0, 5, rot_y=90)
    _close(mid, (5.0, 0.0, 0.0))
    _close(tuple(base[i] + mid[i] for i in range(3)), (-24.0, 0.0, 70.0))

    mapped = _normalize_cad_args(
        "cylinder",
        (),
        {"name": "ShoulderJoint_L", "radius": 9, "height": 10, "center": (-24, 0, 70), "rot_y": 90},
    )
    assert abs(mapped["pos_x"] + 29.0) < 1e-9
    assert abs(mapped["pos_y"]) < 1e-9
    assert abs(mapped["pos_z"] - 70.0) < 1e-9
    assert mapped["rot_y"] == 90

    # 经 runtime 调用时参数会传到 create_cylinder
    captured = {}

    def fake_cyl(doc, name="Cyl", radius=5, height=10, **kw):
        captured.update({"name": name, "radius": radius, "height": height, **kw})
        return {"object": name, "type": "Part::Cylinder"}

    res = run_cad_program(
        'cad.cylinder(name="SJ", radius=9, height=10, center=(-24,0,70), rot_y=90)',
        doc=object(),
        registry={"create_cylinder": fake_cyl},
    )
    assert res["success"] is True, res
    assert abs(captured["pos_x"] + 29.0) < 1e-9
    assert abs(captured["pos_y"]) < 1e-9
    assert abs(captured["pos_z"] - 70.0) < 1e-9
    assert captured["rot_y"] == 90


def test_cone_center_accounts_for_rotation():
    from app.cad_program.runtime import _normalize_cad_args

    mapped = _normalize_cad_args(
        "cone",
        (),
        {"radius1": 10, "radius2": 0, "height": 20, "center": (0, 0, 0), "rot_x": 90},
    )
    # rot_x=90: (0,0,10) → (0,-10,0); Base = (0,10,0)
    assert abs(mapped["pos_x"]) < 1e-9
    assert abs(mapped["pos_y"] - 10.0) < 1e-9
    assert abs(mapped["pos_z"]) < 1e-9


def test_move_accepts_positional_and_xyz_aliases():
    from app.cad_program.runtime import _normalize_cad_args

    m1 = _normalize_cad_args("move", ("Chest", 0, -25, 55), {})
    assert m1["target"] == "Chest"
    assert m1["dx"] == 0.0 and m1["dy"] == -25.0 and m1["dz"] == 55.0

    m2 = _normalize_cad_args("move", ("Pelvis",), {"x": 0, "y": -20, "z": 0})
    assert m2["target"] == "Pelvis"
    assert m2["dx"] == 0.0 and m2["dy"] == -20.0 and m2["dz"] == 0.0
    assert "x" not in m2 and "y" not in m2 and "z" not in m2

    m3 = _normalize_cad_args("move", ("A",), {"offset": (1, 2, 3)})
    assert m3["dx"] == 1.0 and m3["dy"] == 2.0 and m3["dz"] == 3.0

    captured = {}

    def fake_move(doc, target="", dx=0, dy=0, dz=0):
        captured.update({"target": target, "dx": dx, "dy": dy, "dz": dz})
        return {"object": target}

    res = run_cad_program(
        'cad.move("Chest", 0, -25, 55)\ncad.move("Pelvis", x=0, y=-20, z=0)',
        doc=object(),
        registry={"move": fake_move},
    )
    assert res["success"] is True, res
    # 最后一次调用
    assert captured["target"] == "Pelvis"
    assert captured["dy"] == -20.0
