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


def test_rejects_code_that_fails_server_validation():
    res = run_cad_program("import os", doc=object(), registry={})
    assert res["success"] is False
    assert res["error_type"] in ("validation_error", "syntax_error", "forbidden")
