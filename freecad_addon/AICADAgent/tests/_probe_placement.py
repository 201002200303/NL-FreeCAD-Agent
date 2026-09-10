import FreeCAD

# Probe Placement.rotate semantics
p = FreeCAD.Placement(FreeCAD.Vector(27, 0, 0), FreeCAD.Rotation())
print("before", p.Base, p.Rotation.Angle)
p.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 90)
print("after rotate around origin 90deg", [round(p.Base.x, 3), round(p.Base.y, 3), round(p.Base.z, 3)], "angle", round(p.Rotation.Angle * 180 / 3.14159, 2))

p2 = FreeCAD.Placement(FreeCAD.Vector(27, 0, 0), FreeCAD.Rotation())
# alternate: multiply
rot = FreeCAD.Placement(FreeCAD.Vector(), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 90))
# orbit: T(c) * R * T(-c) * P — but for orbiting Base around origin:
# new_base = R * old_base
p3 = FreeCAD.Placement(FreeCAD.Vector(27, 0, 0), FreeCAD.Rotation())
R = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 90)
new_base = R.multVec(p3.Base)
p3.Base = new_base
p3.Rotation = R.multiply(p3.Rotation)
print("manual orbit", [round(p3.Base.x, 3), round(p3.Base.y, 3), round(p3.Base.z, 3)])
