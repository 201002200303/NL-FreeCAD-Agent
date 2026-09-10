# placement_tools.py — Relative placement: align / place_relative / distribute

import FreeCAD

from AICADAgent.cad_tools._helpers import get_object, get_shape
from AICADAgent.geometry_facts import exact_bbox


def _world_bbox(obj):
    """Return tight world bbox; fallback to getBoundBox()."""
    try:
        shape = get_shape(obj)
        return exact_bbox(shape)
    except Exception:
        pass
    return obj.getBoundBox()


def _axis_index(axis: str) -> int:
    mapping = {"x": 0, "y": 1, "z": 2}
    key = str(axis or "z").lower()
    if key not in mapping:
        raise ValueError(f"axis must be x/y/z, got {axis}")
    return mapping[key]


def align_objects(doc, target="", reference="", axis="z", mode="stack", offset=0):
    """Align target to reference on one axis using world bbox.

    mode:
      min / max / center — match that side of reference
      stack — place target's min against reference's max (stack beside/on top)
    """
    tgt = get_object(doc, target)
    ref = get_object(doc, reference)
    bb_t = _world_bbox(tgt)
    bb_r = _world_bbox(ref)
    ax = _axis_index(axis)
    off = float(offset)
    mode = str(mode or "stack").lower()

    t_min = (bb_t.XMin, bb_t.YMin, bb_t.ZMin)[ax]
    t_max = (bb_t.XMax, bb_t.YMax, bb_t.ZMax)[ax]
    t_center = (bb_t.Center.x, bb_t.Center.y, bb_t.Center.z)[ax]
    r_min = (bb_r.XMin, bb_r.YMin, bb_r.ZMin)[ax]
    r_max = (bb_r.XMax, bb_r.YMax, bb_r.ZMax)[ax]
    r_center = (bb_r.Center.x, bb_r.Center.y, bb_r.Center.z)[ax]

    if mode == "min":
        delta = (r_min + off) - t_min
    elif mode == "max":
        delta = (r_max + off) - t_max
    elif mode == "center":
        delta = (r_center + off) - t_center
    elif mode == "stack":
        delta = (r_max + off) - t_min
    else:
        raise ValueError(f"mode must be min/max/center/stack, got {mode}")

    moved = [0.0, 0.0, 0.0]
    moved[ax] = float(delta)
    plm = tgt.Placement
    plm.Base = plm.Base + FreeCAD.Vector(*moved)
    tgt.Placement = plm
    return {
        "tool": "align_objects",
        "object": tgt.Name,
        "reference": ref.Name,
        "axis": str(axis).lower(),
        "mode": mode,
        "moved_by": moved,
        "kind": "act",
    }


def place_relative(doc, target="", reference="", anchor="center", dx=0, dy=0, dz=0):
    """Move target so its bbox center lands on reference's anchor + offset."""
    tgt = get_object(doc, target)
    ref = get_object(doc, reference)
    bb_t = _world_bbox(tgt)
    bb_r = _world_bbox(ref)
    anchor = str(anchor or "center").lower()

    anchors = {
        "center": (bb_r.Center.x, bb_r.Center.y, bb_r.Center.z),
        "top": (bb_r.Center.x, bb_r.Center.y, bb_r.ZMax),
        "bottom": (bb_r.Center.x, bb_r.Center.y, bb_r.ZMin),
        "left": (bb_r.XMin, bb_r.Center.y, bb_r.Center.z),
        "right": (bb_r.XMax, bb_r.Center.y, bb_r.Center.z),
        "front": (bb_r.Center.x, bb_r.YMin, bb_r.Center.z),
        "back": (bb_r.Center.x, bb_r.YMax, bb_r.Center.z),
    }
    if anchor not in anchors:
        raise ValueError(
            f"anchor must be one of {list(anchors)}, got {anchor}"
        )
    ax, ay, az = anchors[anchor]
    desired = FreeCAD.Vector(
        float(ax) + float(dx),
        float(ay) + float(dy),
        float(az) + float(dz),
    )
    current = FreeCAD.Vector(bb_t.Center.x, bb_t.Center.y, bb_t.Center.z)
    delta = desired - current
    plm = tgt.Placement
    plm.Base = plm.Base + delta
    tgt.Placement = plm
    return {
        "tool": "place_relative",
        "object": tgt.Name,
        "reference": ref.Name,
        "anchor": anchor,
        "moved_by": [delta.x, delta.y, delta.z],
        "kind": "act",
    }


def distribute_along(doc, targets="", axis="x", spacing=10):
    """Distribute named objects along an axis with equal spacing (first fixed)."""
    if isinstance(targets, str):
        names = [n.strip() for n in targets.split(",") if n.strip()]
    elif isinstance(targets, (list, tuple)):
        names = [str(n).strip() for n in targets if str(n).strip()]
    else:
        raise ValueError("targets must be comma-separated string or list")
    if len(names) < 2:
        raise ValueError("distribute_along needs at least 2 targets")

    ax = _axis_index(axis)
    gap = float(spacing)
    objs = [get_object(doc, n) for n in names]
    first_bb = _world_bbox(objs[0])
    cursor = (first_bb.XMax, first_bb.YMax, first_bb.ZMax)[ax]
    moved_list = []

    for obj in objs[1:]:
        bb = _world_bbox(obj)
        t_min = (bb.XMin, bb.YMin, bb.ZMin)[ax]
        desired_min = cursor + gap
        delta_val = desired_min - t_min
        moved = [0.0, 0.0, 0.0]
        moved[ax] = float(delta_val)
        plm = obj.Placement
        plm.Base = plm.Base + FreeCAD.Vector(*moved)
        obj.Placement = plm
        bb2 = _world_bbox(obj)
        cursor = (bb2.XMax, bb2.YMax, bb2.ZMax)[ax]
        moved_list.append({"object": obj.Name, "moved_by": moved})

    return {
        "tool": "distribute_along",
        "object": names[0],
        "targets": names,
        "axis": str(axis).lower(),
        "spacing": gap,
        "moves": moved_list,
        "kind": "act",
    }
