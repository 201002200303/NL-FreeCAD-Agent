# partdesign_tools.py — PartDesign Pad / Pocket / Revolution
# API ref: PartDesign::Pad — Profile, Length, Type, UpToFace

import FreeCAD
import Part

from AICADAgent.cad_tools._helpers import get_object, get_shape


def pad_sketch(doc, name="Pad", sketch="", length=10, body=None,
               reversed=False, midplane=False, type="Length"):
    """Extrude a sketch (PartDesign::Pad). type: Length | TwoLengths | UpToLast | UpToFirst."""
    if body:
        container = get_object(doc, body)
        pad = container.newObject("PartDesign::Pad", name)
    else:
        pad = doc.addObject("PartDesign::Pad", name)
    pad.Label = name
    pad.Profile = get_object(doc, sketch)
    pad.Length = float(length)
    pad.Reversed = bool(reversed)
    # FC 1.1+ deprecates Midplane in favor of SideType
    if hasattr(pad, "SideType"):
        pad.SideType = "Two sides" if midplane else "One side"
    else:
        pad.Midplane = bool(midplane)
    if hasattr(pad, "Type"):
        pad.Type = type
    return {"tool": "pad_sketch", "object": pad.Name, "sketch": sketch, "length": length, "type": "PartDesign::Pad"}


def pocket_sketch(doc, name="Pocket", sketch="", length=10, body=None, reversed=False, type="Length"):
    """Cut extrude a sketch (PartDesign::Pocket)."""
    if body:
        container = get_object(doc, body)
        pocket = container.newObject("PartDesign::Pocket", name)
    else:
        pocket = doc.addObject("PartDesign::Pocket", name)
    pocket.Label = name
    pocket.Profile = get_object(doc, sketch)
    pocket.Length = float(length)
    pocket.Reversed = bool(reversed)
    if hasattr(pocket, "Type"):
        pocket.Type = type
    return {"tool": "pocket_sketch", "object": pocket.Name, "sketch": sketch, "type": "PartDesign::Pocket"}


def pad_to_face(doc, name="Pad", sketch="", target="", face="Face1", length=10, body=None, offset=0):
    """Pad sketch up to a face on target solid (sets UpToFace link).

    PartDesign scope: UpToFace target must live in the same Body as the Pad.
    If target is outside the body, fall back to Length extrusion (with note).
    """
    target_obj = get_object(doc, target)
    face_name = face if str(face).startswith("Face") else f"Face{int(face)}"
    if body:
        container = get_object(doc, body)
        pad = container.newObject("PartDesign::Pad", name)
    else:
        pad = doc.addObject("PartDesign::Pad", name)
    pad.Label = name
    pad.Profile = get_object(doc, sketch)

    same_body = False
    if body:
        try:
            same_body = target_obj.getParentGeoFeatureGroup() is container
        except Exception:
            same_body = False
    else:
        same_body = True

    note = None
    if same_body:
        pad.Type = "UpToFace"
        pad.UpToFace = (target_obj, [face_name])
        if hasattr(pad, "Offset"):
            pad.Offset = float(offset)
    else:
        # External Part::Box etc. cannot be UpToFace targets inside a Body
        pad.Type = "Length"
        pad.Length = float(length)
        note = (
            f"target '{target}' not in body '{body}'; "
            f"fell back to Length={length} (UpToFace requires same Body)"
        )

    return {
        "tool": "pad_to_face",
        "object": pad.Name,
        "sketch": sketch,
        "target": target,
        "face": face_name,
        "type": "PartDesign::Pad",
        "note": note,
    }


def revolve_sketch(doc, name="Revolution", sketch="", axis_x=0, axis_y=0, axis_z=1,
                   angle=360, body=None):
    """Revolve sketch around axis (PartDesign::Revolution)."""
    sk = get_object(doc, sketch)
    if body:
        container = get_object(doc, body)
        rev = container.newObject("PartDesign::Revolution", name)
    else:
        rev = doc.addObject("PartDesign::Revolution", name)
    rev.Label = name
    rev.Profile = sk
    rev.Angle = float(angle)

    axis_vec = FreeCAD.Vector(float(axis_x), float(axis_y), float(axis_z))
    if axis_vec.Length == 0:
        axis_vec = FreeCAD.Vector(0, 0, 1)
    axis_vec.normalize()

    # FC 1.x uses ReferenceAxis (sketch/body datum), not a free Vector Axis
    axis_name = "V_Axis"
    if abs(axis_vec.x) >= abs(axis_vec.y) and abs(axis_vec.x) >= abs(axis_vec.z):
        axis_name = "H_Axis" if abs(axis_vec.x) > 0.5 else "V_Axis"
    elif abs(axis_vec.y) >= abs(axis_vec.z):
        axis_name = "H_Axis"
    else:
        axis_name = "V_Axis"

    if hasattr(rev, "ReferenceAxis"):
        try:
            rev.ReferenceAxis = (sk, [axis_name])
        except Exception:
            rev.ReferenceAxis = (sk, ["V_Axis"])
    elif hasattr(rev, "Axis"):
        rev.Axis = axis_vec
    else:
        raise ValueError("Current FreeCAD version cannot set a revolve axis")
    return {
        "tool": "revolve_sketch",
        "object": rev.Name,
        "sketch": sketch,
        "angle": angle,
        "axis": axis_name,
        "type": "PartDesign::Revolution",
    }


def extrude_sketch(doc, name="Extrude", sketch="", length=10, direction_x=0, direction_y=0, direction_z=1):
    """Part workbench style: extrude sketch wire without PartDesign Body."""
    sk = get_object(doc, sketch)
    shape = sk.Shape if hasattr(sk, "Shape") else Part.getShape(sk, "")
    if shape.Faces:
        profile = shape.Faces[0]
    elif shape.Wires:
        profile = Part.Face(shape.Wires[0])
    else:
        raise ValueError(f"Sketch '{sketch}' has no closed profile to extrude")
    vec = FreeCAD.Vector(float(direction_x), float(direction_y), float(direction_z))
    if vec.Length == 0:
        vec = FreeCAD.Vector(0, 0, 1)
    vec.normalize()
    vec = vec * float(length)
    solid = profile.extrude(vec)
    feat = doc.addObject("Part::Feature", name)
    feat.Label = name
    feat.Shape = solid
    return {"tool": "extrude_sketch", "object": feat.Name, "sketch": sketch, "type": "Part::Feature"}
