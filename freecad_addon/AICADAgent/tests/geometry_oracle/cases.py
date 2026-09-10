"""Geometry oracle case table (L3 = direct registry, L4 = cad.* path).

Expectations are derived by hand from FreeCAD semantics
(https://wiki.freecad.org/Placement, Part primitives, and this repo's documented
anchor/axis conventions) — never from observed output.  A failing case is a
finding, not something to re-baseline.

Schema
------
id      unique case name
layer   "L3" (TOOL_REGISTRY direct) or "L4" (execute_cad_program / cad.*)
code    L4: restricted cad.* program
tool    L3: registry tool name
args    L3: registry kwargs
object  expected object name (L4: required; L3: optional, else tool result)
expect  bbox_size / bbox_center / solids / volume_range / axis_along / valid
ref     which FreeCAD fact the expectation comes from
"""

CASES: list[dict] = [
    # ── L4: box anchor / center mapping ────────────────────────────────
    {
        "id": "l4_box_center_anchor",
        "layer": "L4",
        "code": 'cad.box(name="B", size=(40, 20, 10), center=(0, 0, 5))\n',
        "object": "B",
        "expect": {"bbox_size": [40, 20, 10], "bbox_center": [0, 0, 5], "solids": 1},
        "ref": "cad.box center= is geometric center (runtime sets anchor=center)",
    },
    # ── L4: cylinder default axis and rot_* ────────────────────────────
    {
        "id": "l4_cylinder_default_axis_z",
        "layer": "L4",
        "code": 'cad.cylinder(name="C", radius=10, height=30, center=(0, 0, 15))\n',
        "object": "C",
        "expect": {
            "bbox_size": [20, 20, 30],
            "bbox_center": [0, 0, 15],
            "axis_along": "Z",
            "solids": 1,
        },
        "ref": "Part::Cylinder is along local +Z; no rot means vertical",
    },
    {
        "id": "l4_cylinder_rot_y_90_side_wheel",
        "layer": "L4",
        "code": 'cad.cylinder(name="W", radius=20, height=8, center=(0, 0, 10), rot_y=90)\n',
        "object": "W",
        "expect": {
            "bbox_size": [8, 40, 40],
            "bbox_center": [0, 0, 10],
            "axis_along": "X",
            "solids": 1,
        },
        "ref": "rot_y=90 puts the cylinder axis along +X; center= must survive rotation",
    },
    {
        "id": "l4_cylinder_rot_x_90_axis_y",
        "layer": "L4",
        "code": 'cad.cylinder(name="V", radius=15, height=6, center=(0, 0, 10), rot_x=90)\n',
        "object": "V",
        "expect": {
            "bbox_size": [30, 6, 30],
            "bbox_center": [0, 0, 10],
            "axis_along": "Y",
            "solids": 1,
        },
        "ref": "rot_x=90 puts the cylinder axis along +Y",
    },
    # ── L4: cone ───────────────────────────────────────────────────────
    {
        "id": "l4_cone_default_axis_z",
        "layer": "L4",
        "code": 'cad.cone(name="K", radius1=10, radius2=0, height=30, center=(0, 0, 15))\n',
        "object": "K",
        "expect": {
            "bbox_size": [20, 20, 30],
            "bbox_center": [0, 0, 15],
            "axis_along": "Z",
            "solids": 1,
        },
        "ref": "Part::Cone axis +Z; center= is mid-height, not the bottom face",
    },
    # ── L4: rotate pivot semantics ─────────────────────────────────────
    {
        "id": "l4_rotate_default_pivot_world_origin",
        "layer": "L4",
        "code": (
            'b = cad.box(name="B", size=(10, 10, 10), center=(10, 0, 5))\n'
            'cad.rotate(b, axis="Z", angle=90)\n'
        ),
        "object": "B",
        "expect": {"bbox_size": [10, 10, 10], "bbox_center": [0, 10, 5], "solids": 1},
        "ref": "rotate pivot defaults to world origin, so the body orbits to (0,10)",
    },
    {
        "id": "l4_rotate_about_own_center",
        "layer": "L4",
        "code": (
            'b = cad.box(name="B", size=(10, 10, 10), center=(10, 0, 5))\n'
            'cad.rotate(b, axis="Z", angle=90, center=(10, 0, 5))\n'
        ),
        "object": "B",
        "expect": {"bbox_size": [10, 10, 10], "bbox_center": [10, 0, 5], "solids": 1},
        "ref": "center=/pivot= gives self-rotation; position must not move",
    },
    # ── L4: hole axis ──────────────────────────────────────────────────
    {
        "id": "l4_hole_axis_z",
        "layer": "L4",
        "code": (
            'base = cad.box(name="Base", size=(40, 40, 10), center=(0, 0, 5))\n'
            'cad.hole(target=base, hole_diameter=10, axis="Z", result_name="BaseHole")\n'
        ),
        "object": "BaseHole",
        "expect": {
            "bbox_size": [40, 40, 10],
            "solids": 1,
            "volume_range": [15000, 15500],
        },
        "ref": "hole axis=Z bores through the 10mm thickness: 40*40*10 - pi*5^2*10",
    },
    # ── L4: boolean ────────────────────────────────────────────────────
    {
        "id": "l4_fuse_two_overlapping_boxes",
        "layer": "L4",
        "code": (
            'a = cad.box(name="A", size=(20, 20, 20), center=(0, 0, 10))\n'
            'b = cad.box(name="B", size=(20, 20, 20), center=(10, 0, 10))\n'
            'cad.fuse(a, b, name="Union")\n'
        ),
        "object": "Union",
        "expect": {"solids": 1, "volume_range": [11800, 12200]},
        "ref": "union of two 8000mm^3 boxes overlapping 4000mm^3 = 12000mm^3",
    },
    {
        "id": "l4_cut_cylindrical_bore",
        "layer": "L4",
        "code": (
            'blk = cad.box(name="Blk", size=(20, 20, 20), center=(0, 0, 10))\n'
            'cyl = cad.cylinder(name="Tool", radius=5, height=30, center=(0, 0, 10))\n'
            'cad.cut(blk, cyl, name="BlkCut")\n'
        ),
        "object": "BlkCut",
        "expect": {"solids": 1, "volume_range": [6350, 6500]},
        "ref": "8000 - pi*5^2*20 = 6429mm^3",
    },
    # ── L4: patterns ───────────────────────────────────────────────────
    {
        "id": "l4_polar_pattern_axis_z",
        "layer": "L4",
        "code": (
            'hub = cad.cylinder(name="Hub", radius=4, height=10, center=(10, 0, 5))\n'
            'cad.polar_pattern(hub, count=4, angle=360, axis="Z", '
            'name_prefix="Hub", fuse=True, fuse_name="HubRing")\n'
        ),
        "object": "HubRing",
        "expect": {
            "bbox_size": [28, 28, 10],
            "bbox_center": [0, 0, 5],
            "solids": 4,
        },
        "ref": (
            "r=4 hub at radius 10, 4 disjoint instances: span +-14, height 10; "
            "disjoint solids stay 4 solids inside one Fusion object — a phase must "
            "not require solid_count==1 for a pattern of separated parts"
        ),
    },
    {
        "id": "l4_linear_pattern_axis_x",
        "layer": "L4",
        "code": (
            'bar = cad.box(name="Bar", size=(5, 5, 5), center=(0, 0, 2.5))\n'
            'cad.linear_pattern(bar, count=4, offset=(12, 0, 0), '
            'name_prefix="Bar", fuse=True, fuse_name="BarRow")\n'
        ),
        "object": "BarRow",
        "expect": {
            "bbox_size": [41, 5, 5],
            "bbox_center": [18, 0, 2.5],
            "solids": 4,
        },
        "ref": (
            "4 bars at x=0/12/24/36, each 5 wide: span -2.5..38.5; separated "
            "instances remain 4 solids even with fuse=True"
        ),
    },
    # ── L4: sketch + extrude direction ─────────────────────────────────
    {
        "id": "l4_extrude_xy_default_direction_z",
        "layer": "L4",
        "code": (
            'sk = cad.sketch(name="Sk", plane="XY")\n'
            'cad.circle(sk, 0, 0, 5)\n'
            'cad.extrude(name="Pad", sketch=sk, length=20)\n'
        ),
        "object": "Pad",
        "expect": {"bbox_size": [10, 10, 20], "solids": 1},
        "ref": "extrude default direction +Z: r=5 circle becomes 20mm tall",
    },
    {
        "id": "l4_extrude_xz_rect_direction_y",
        "layer": "L4",
        "code": (
            'sk = cad.sketch(name="Sk", plane="XZ")\n'
            'cad.rect(sk, -10, -15, 20, 30)\n'
            'cad.extrude(name="Pad", sketch=sk, length=10, direction=(0, 1, 0))\n'
        ),
        "object": "Pad",
        "expect": {"bbox_size": [20, 10, 30], "solids": 1},
        "ref": "XZ sketch 20x30 stretched 10 along +Y (direction must be explicit)",
    },
    # ── L3: direct registry anchor/axis facts ──────────────────────────
    {
        "id": "l3_create_box_anchor_min",
        "layer": "L3",
        "tool": "create_box",
        "args": {"name": "B", "length": 40, "width": 20, "height": 10, "anchor": "min"},
        "expect": {"bbox_size": [40, 20, 10], "bbox_center": [20, 10, 5]},
        "ref": "Part::Box Placement.Base is the corner when anchor=min",
    },
    {
        "id": "l3_create_box_anchor_center",
        "layer": "L3",
        "tool": "create_box",
        "args": {
            "name": "B",
            "length": 40,
            "width": 20,
            "height": 10,
            "anchor": "center",
            "pos_x": 0,
            "pos_y": 0,
            "pos_z": 5,
        },
        "expect": {"bbox_size": [40, 20, 10], "bbox_center": [0, 0, 5]},
        "ref": "anchor=center places the geometric center at pos",
    },
    {
        "id": "l3_create_torus_default_axis_z",
        "layer": "L3",
        "tool": "create_torus",
        "args": {"name": "T", "radius1": 20, "radius2": 5},
        "expect": {"bbox_size": [50, 50, 10], "axis_along": "Z"},
        "ref": "Part::Torus major ring lies in local XY; thickness is 2*radius2",
    },
    {
        "id": "l3_create_torus_rot_x_90_axis_y",
        "layer": "L3",
        "tool": "create_torus",
        "args": {"name": "T", "radius1": 20, "radius2": 5, "rot_x": 90},
        "expect": {"bbox_size": [50, 10, 50], "axis_along": "Y"},
        "ref": "rot_x=90 stands the major ring up: axis moves from Z to Y",
    },
]
