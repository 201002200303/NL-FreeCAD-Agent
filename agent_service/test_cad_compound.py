"""cad.compound：整机装配的组合语义（不做布尔、不删源件）。

背景：整机若用 fuse 装配，boolean_tools 会删除源零件，导致后续阶段验收
找不到 Leg_R / Arm_R 等中间件（实测高达会话因此在「fuse → 删源件 → 验收失败
→ 重建」之间死循环）。compound 只把零件装进一个容器，源件必须保留。
"""
from app.cad_program.manifest import CAD_TO_TOOL
from app.cad_program.runtime import _normalize_cad_args, run_cad_program
from app.tools.tool_specs import TOOL_SPECS


def _registry(calls, delete_calls=None):
    def fake_box(doc, name="Box", **kw):
        calls.append(("create_box", {"name": name}))
        return {"object": name}

    def fake_compound(doc, name="Compound", targets=None):
        calls.append(("make_compound", {"name": name, "targets": list(targets or [])}))
        return {"object": name, "sources": list(targets or [])}

    reg = {"create_box": fake_box, "make_compound": fake_compound}

    if delete_calls is not None:
        def fake_delete(doc, target=""):
            delete_calls.append(target)
            return {"object": target, "deleted": True}

        reg["delete_object"] = fake_delete
    return reg


def test_compound_is_model_visible_and_specced():
    assert CAD_TO_TOOL["compound"] == "make_compound"
    assert "make_compound" in TOOL_SPECS


def test_compound_accepts_operand_list():
    calls: list = []
    code = (
        'cad.box(name="Leg_L", size=(20,30,112), center=(-30,0,56))\n'
        'cad.box(name="Torso", size=(48,30,40), center=(0,0,137))\n'
        'cad.compound(["Leg_L", "Torso"], name="Mecha")\n'
    )
    res = run_cad_program(code, doc=object(), registry=_registry(calls))
    assert res["success"] is True, res
    assert calls[-1] == ("make_compound", {"name": "Mecha", "targets": ["Leg_L", "Torso"]})


def test_compound_accepts_positional_operands():
    calls: list = []
    code = (
        'cad.box(name="A", size=(1,1,1), center=(0,0,0))\n'
        'cad.box(name="B", size=(1,1,1), center=(5,0,0))\n'
        'cad.compound("A", "B", name="Asm")\n'
    )
    res = run_cad_program(code, doc=object(), registry=_registry(calls))
    assert res["success"] is True, res
    assert calls[-1] == ("make_compound", {"name": "Asm", "targets": ["A", "B"]})


def test_compound_returns_object_name_for_downstream_use():
    calls: list = []
    code = (
        'a = cad.box(name="A", size=(1,1,1), center=(0,0,0))\n'
        'b = cad.box(name="B", size=(1,1,1), center=(5,0,0))\n'
        'asm = cad.compound([a, b], name="Asm")\n'
    )
    res = run_cad_program(code, doc=object(), registry=_registry(calls))
    assert res["success"] is True, res
    # 变量必须是对象名字符串，而不是 handler 的原始 dict
    assert calls[-1][1]["name"] == "Asm"
    assert res["created"] == ["A", "B", "Asm"]


def test_compound_does_not_delete_its_sources():
    """这是与 fuse 的核心差别：源零件必须留在文档里。"""
    calls: list = []
    deletes: list = []

    class Doc:
        def getObject(self, name):
            return None

    code = (
        'cad.box(name="Leg_L", size=(20,30,112), center=(-30,0,56))\n'
        'cad.box(name="Torso", size=(48,30,40), center=(0,0,137))\n'
        'cad.compound(["Leg_L", "Torso"], name="Mecha")\n'
    )
    res = run_cad_program(code, doc=Doc(), registry=_registry(calls, deletes))
    assert res["success"] is True, res
    assert "Leg_L" not in deletes
    assert "Torso" not in deletes


def test_compound_replaces_same_named_result_only():
    calls: list = []
    deletes: list = []

    class Doc:
        def getObject(self, name):
            return object() if name == "Mecha" else None

    code = (
        'cad.box(name="A", size=(1,1,1), center=(0,0,0))\n'
        'cad.box(name="B", size=(1,1,1), center=(5,0,0))\n'
        'cad.compound(["A", "B"], name="Mecha")\n'
    )
    res = run_cad_program(code, doc=Doc(), registry=_registry(calls, deletes))
    assert res["success"] is True, res
    assert deletes == ["Mecha"]


def test_compound_normalization_when_targets_given_as_kwarg():
    mapped = _normalize_cad_args("compound", (), {"name": "Asm", "targets": ["A", "B"]})
    assert mapped["name"] == "Asm"
    assert mapped["targets"] == ["A", "B"]
