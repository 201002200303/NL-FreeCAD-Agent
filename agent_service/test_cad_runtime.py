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


def test_boolean_accepts_operand_list_and_folds():
    """D7：cad.fuse([a,b,c]) 要折叠成两两布尔，不能把列表直接丢给底层。"""
    fuse_calls: list[dict] = []
    cut_calls: list[dict] = []

    def fake_fuse(doc, name="Fuse", base="", tool=""):
        fuse_calls.append({"name": name, "base": base, "tool": tool})
        return {"object": name}

    def fake_cut(doc, name="Cut", base="", tool=""):
        cut_calls.append({"name": name, "base": base, "tool": tool})
        return {"object": name}

    registry = {
        "create_box": lambda doc, **kw: {"object": kw.get("name")},
        "boolean_fuse": fake_fuse,
        "boolean_cut": fake_cut,
    }
    code = (
        'cad.box(name="A", size=(10,10,10), center=(0,0,0))\n'
        'cad.box(name="B", size=(10,10,10), center=(5,0,0))\n'
        'cad.box(name="C", size=(10,10,10), center=(10,0,0))\n'
        'cad.box(name="D", size=(4,4,4), center=(0,0,0))\n'
        'fused = cad.fuse(["A", "B", "C"], name="Fused")\n'
        'cad.cut(fused, "D", name="CutFinal")\n'
    )
    res = run_cad_program(code, doc=object(), registry=registry)
    assert res["success"] is True, res
    assert [(c["base"], c["tool"]) for c in fuse_calls] == [("A", "B"), ("Fused_tmp1", "C")]
    assert fuse_calls[-1]["name"] == "Fused"
    # 折叠结果必须返回对象名字符串（能被下一次布尔当操作数用），而不是 handler 的原始 dict
    assert cut_calls == [{"name": "CutFinal", "base": "Fused", "tool": "D"}]


def test_boolean_extra_positional_operands_are_not_dropped():
    """D7：cad.fuse(a, b, c) 曾经静默丢掉第 3 个操作数，产出错误几何。"""
    calls: list[tuple[str, str]] = []

    def fake_fuse(doc, name="Fuse", base="", tool=""):
        calls.append((base, tool))
        return {"object": name}

    registry = {
        "create_box": lambda doc, **kw: {"object": kw.get("name")},
        "boolean_fuse": fake_fuse,
    }
    code = (
        'cad.box(name="A", size=(10,10,10), center=(0,0,0))\n'
        'cad.box(name="B", size=(10,10,10), center=(5,0,0))\n'
        'cad.box(name="C", size=(10,10,10), center=(10,0,0))\n'
        'cad.fuse("A", "B", "C", name="Fused")\n'
    )
    res = run_cad_program(code, doc=object(), registry=registry)
    assert res["success"] is True, res
    assert calls == [("A", "B"), ("Fused_tmp1", "C")]


def test_boolean_single_operand_reports_actionable_hint():
    """单操作数应在调用前给出可修复的错误，而不是底层 a string or integer required。"""
    def fake_fuse(doc, name="Fuse", base="", tool=""):  # pragma: no cover - 不应被调用
        raise AssertionError("handler must not run for invalid operand count")

    registry = {
        "create_box": lambda doc, **kw: {"object": kw.get("name")},
        "boolean_fuse": fake_fuse,
    }
    res = run_cad_program(
        'cad.box(name="A", size=(1,1,1), center=(0,0,0))\ncad.fuse("A")\n',
        doc=object(),
        registry=registry,
    )
    assert res["success"] is False
    message = res["error_message"]
    assert "cad.fuse" in message
    assert "至少" in message
    assert "cad.fuse" in message and "(" in message  # 建议写法
    assert res["failed_line"]


def test_server_and_plugin_runtime_stay_in_sync():
    """两端 runtime 手工镜像：除 import 前缀外必须逐字一致，否则同一 cad.* 行为会漂移。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    server = (root / "agent_service" / "app" / "cad_program" / "runtime.py").read_text(encoding="utf-8")
    plugin = (root / "freecad_addon" / "AICADAgent" / "cad_program" / "runtime.py").read_text(encoding="utf-8")
    normalized = server.replace("from app.cad_program.", "from AICADAgent.cad_program.")
    assert normalized.replace("\r\n", "\n") == plugin.replace("\r\n", "\n"), (
        "server/plugin cad runtime 已漂移，请同步两端"
    )


def test_export_accepts_positional_and_common_alias_params():
    """B4 回归：导出参数名不可猜，模型曾连续 4 轮试 path=/filename=/位置参数全都失败。

    工具真实签名是 filepath=；normalize 必须收敛别名并接受位置参数。
    """
    from app.cad_program.runtime import _normalize_cad_args

    m1 = _normalize_cad_args("export_step", ("Gundam", "Gundam.step"), {})
    assert m1["target"] == "Gundam"
    assert m1["filepath"] == "Gundam.step"

    m2 = _normalize_cad_args("export_step", ("Gundam",), {"path": "Gundam.step"})
    assert m2["target"] == "Gundam" and m2["filepath"] == "Gundam.step"

    m3 = _normalize_cad_args("export_step", ("Gundam",), {"filename": "Gundam.step"})
    assert m3["target"] == "Gundam" and m3["filepath"] == "Gundam.step"

    m4 = _normalize_cad_args(
        "export_step", (), {"target": "Gundam", "filepath": "Gundam.step"}
    )
    assert m4["filepath"] == "Gundam.step"

    # 单个位置参数且形如文件名 ⇒ 整文档导出，它是 filepath 不是 target
    m5 = _normalize_cad_args("export_step", ("out.step",), {})
    assert m5.get("filepath") == "out.step" and "target" not in m5

    # 整文档导出 + 显式 filepath 关键字
    m6 = _normalize_cad_args("export_stl", (), {"filepath": "out.stl", "tolerance": 0.05})
    assert m6["filepath"] == "out.stl" and m6["tolerance"] == 0.05

    # target 的常见别名
    m7 = _normalize_cad_args("export_step", (), {"objects": ["A", "B"], "filepath": "x.step"})
    assert m7["target"] == ["A", "B"]


def test_export_handler_receives_resolved_filepath():
    """端到端：位置参数必须真的传到底层 handler，而不是被静默丢掉。"""
    captured = {}

    def fake_export(doc, target="", filepath=""):
        captured.update({"target": target, "filepath": filepath})
        return {"object": target, "filepath": filepath}

    res = run_cad_program(
        'cad.export_step("Gundam", "Gundam.step")',
        doc=object(),
        registry={"export_step": fake_export},
    )
    assert res["success"] is True, res
    assert captured == {"target": "Gundam", "filepath": "Gundam.step"}


def test_export_missing_filepath_reports_actionable_error():
    """缺 filepath 时不能落到 FreeCAD 那句无从下手的 'Writing of STEP failed'。"""
    calls = []

    def fake_export(doc, target="", filepath=""):
        calls.append(1)
        return {}

    res = run_cad_program(
        'cad.export_step(target="Gundam")',
        doc=object(),
        registry={"export_step": fake_export},
    )
    assert res["success"] is False
    assert not calls, "缺 filepath 不应调用底层 handler"
    assert "filepath" in res["error_message"]
