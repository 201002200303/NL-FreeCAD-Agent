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
