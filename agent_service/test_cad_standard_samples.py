"""标准 CAD 样例程序：校验 + mock 运行时必须通过。"""

from app.cad_program.runtime import run_cad_program
from app.cad_program.validate import validate_cad_source


# ── 标准样例（给模型参考的正确写法）────────────────────────────────

SAMPLE_GEAR_KEYWAY = """
# 简化齿轮：polar_pattern 布齿 + 轴孔 + 键槽（禁止 for+rotate）
root = cad.cylinder(name="Root", radius=24, height=10, center=(0, 0, 0))
tooth = cad.box(name="Tooth", size=(6, 6, 10), center=(27, 0, 0))
ring = cad.polar_pattern(tooth, count=12, angle=360, axis="Z", name_prefix="Tooth", fuse=True, fuse_name="ToothRing")
gear = cad.fuse(root, ring)
bore = cad.cylinder(name="Bore", radius=10, height=12, center=(0, 0, 0))
hollow = cad.cut(gear, bore)
key = cad.box(name="Keyway", size=(3.5, 6, 12), center=(11.75, 0, 0))
final = cad.cut(hollow, key)
"""

SAMPLE_STEPPED_SHAFT = """
# 阶梯轴：大端 Ø30×20 + 小端 Ø20×40，轴线 Z
big = cad.cylinder(name="ShaftBig", radius=15, height=20, center=(0, 0, 10))
small = cad.cylinder(name="ShaftSmall", radius=10, height=40, center=(0, 0, 40))
shaft = cad.fuse(big, small)
"""

SAMPLE_BRACKET = """
# 直角支架：底板 + 立板 + 通孔
base = cad.box(name="Base", size=(40, 30, 5), center=(0, 0, 2.5))
wall = cad.box(name="Wall", size=(5, 30, 30), center=(-17.5, 0, 20))
bracket = cad.fuse(base, wall)
hole = cad.cylinder(name="Hole", radius=4, height=20, center=(0, 0, 2.5))
bracket = cad.cut(bracket, hole)
"""

SAMPLE_SYMMETRIC_BOXES = """
# 左右对称：关于 X=0 对侧 create（不用 mirror）
left = cad.box(name="Block_L", size=(10, 10, 10), center=(-20, 0, 5))
right = cad.box(name="Block_R", size=(10, 10, 10), center=(20, 0, 5))
"""

SAMPLE_POLAR_TEETH = """
# 极坐标阵列 8 齿（推荐写法，避免手工 rotate+append）
root = cad.cylinder(name="Root", radius=25, height=12, center=(0, 0, 6))
tooth = cad.box(name="Tooth", size=(8, 5, 12), center=(28, 0, 6))
ring = cad.polar_pattern(target=tooth, count=8, angle=360, axis="Z", name_prefix="Tooth", fuse=True, fuse_name="ToothRing")
gear = cad.fuse(root, ring)
"""

SAMPLES = {
    "gear_keyway": SAMPLE_GEAR_KEYWAY,
    "stepped_shaft": SAMPLE_STEPPED_SHAFT,
    "bracket": SAMPLE_BRACKET,
    "symmetric_boxes": SAMPLE_SYMMETRIC_BOXES,
    "polar_teeth": SAMPLE_POLAR_TEETH,
}


def _mock_registry():
    calls = []

    def box(doc, name="Box", length=10, width=10, height=10, pos_x=0, pos_y=0, pos_z=0, anchor="min", **kw):
        calls.append(("create_box", name))
        return {"object": name}

    def cyl(doc, name="Cyl", radius=5, height=10, pos_x=0, pos_y=0, pos_z=0, **kw):
        calls.append(("create_cylinder", name))
        return {"object": name}

    def fuse(doc, name="Fuse", base="", tool=""):
        calls.append(("boolean_fuse", name))
        return {"object": name}

    def cut(doc, name="Cut", base="", tool=""):
        calls.append(("boolean_cut", name))
        return {"object": name}

    def polar(doc, target="", count=4, angle=360, axis="Z", name_prefix="", fuse=False, fuse_name="", **kw):
        calls.append(("polar_pattern", fuse_name or target))
        return {"object": fuse_name or target, "created": [f"{name_prefix}{i}" for i in range(2, int(count) + 1)]}

    return {
        "create_box": box,
        "create_cylinder": cyl,
        "boolean_fuse": fuse,
        "boolean_cut": cut,
        "polar_pattern": polar,
    }, calls


def test_all_standard_samples_validate():
    for name, code in SAMPLES.items():
        verdict = validate_cad_source(code)
        assert verdict.ok is True, f"{name}: {verdict.violations}"


def test_all_standard_samples_run_on_mock_registry():
    for name, code in SAMPLES.items():
        registry, calls = _mock_registry()
        res = run_cad_program(code, doc=object(), registry=registry)
        assert res["success"] is True, f"{name}: {res}"
        assert res["created"], f"{name}: no created objects"


def test_user_reported_one_liner_also_works():
    code = (
        'g=cad.cylinder(name="GearBody",radius=30,height=10,center=(0,0,0));'
        'b=cad.cylinder(name="Bore",radius=10,height=12,center=(0,0,0));'
        'h=cad.cut(g,b);'
        'k=cad.box(name="Keyway",size=(3.5,6,12),center=(11.75,0,0));'
        'f=cad.cut(h,k)'
    )
    assert validate_cad_source(code).ok is True
    registry, _ = _mock_registry()
    res = run_cad_program(code, doc=object(), registry=registry)
    assert res["success"] is True, res
