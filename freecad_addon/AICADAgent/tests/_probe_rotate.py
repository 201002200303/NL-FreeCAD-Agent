import sys
sys.path.insert(0, r"D:\project_main\NL-FreeCAD-Agent\freecad_addon")
import FreeCAD
from AICADAgent.cad_tools import TOOL_REGISTRY
from AICADAgent.cad_program import run_cad_program

code = """
teeth = []
for i in range(4):
    angle_deg = i * 90
    tooth = cad.box(name=f"T{i}", size=(6,6,10), center=(27,0,0))
    tooth_rot = cad.rotate(tooth, axis="Z", angle=angle_deg, pivot=(0,0,0))
    teeth.append(tooth_rot)
"""
doc = FreeCAD.newDocument("ProbeRot")
res = run_cad_program(code, doc=doc, registry=TOOL_REGISTRY)
print("SUCCESS", res.get("success"), "created", res.get("created"))
print("ERR", res.get("error_message"))
for name in ["T0", "T1", "T2", "T3"]:
    obj = doc.getObject(name)
    if obj is None:
        print(name, "MISSING")
        continue
    bb = obj.Shape.BoundBox
    print(
        name,
        "Placement.Base=",
        [round(obj.Placement.Base.x, 3), round(obj.Placement.Base.y, 3), round(obj.Placement.Base.z, 3)],
        "bbox.center=",
        [
            round((bb.XMin + bb.XMax) / 2, 3),
            round((bb.YMin + bb.YMax) / 2, 3),
            round((bb.ZMin + bb.ZMax) / 2, 3),
        ],
    )
FreeCAD.closeDocument(doc.Name)
