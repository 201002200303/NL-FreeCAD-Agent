"""Canonical model-visible CAD operation catalog.

This file is the single source of truth.  The FreeCAD add-on ships a generated
copy (scripts/sync_cad_manifest.py) because it is installed outside the Agent
process; both copies must stay identical.

`create_wedge` / `make_sweep` stay in TOOL_REGISTRY but are NOT model-visible:
they have no geometric Oracle case yet, so exposing them only buys failed turns.
"""

CAD_TO_TOOL = {
    "box": "create_box",
    "cylinder": "create_cylinder",
    "sphere": "create_sphere",
    "cone": "create_cone",
    "torus": "create_torus",
    "cut": "boolean_cut",
    "fuse": "boolean_fuse",
    "common": "boolean_common",
    "move": "move",
    "rotate": "rotate",
    "scale": "scale",
    "copy": "copy_object",
    "linear_pattern": "linear_pattern",
    "polar_pattern": "polar_pattern",
    "delete": "delete_object",
    "set_property": "modify_param",
    "fillet": "add_fillet",
    "chamfer": "add_chamfer",
    "hole": "cut_hole",
    "sketch": "create_sketch",
    "line": "sketch_add_line",
    "rect": "sketch_add_rect",
    "circle": "sketch_add_circle",
    "arc": "sketch_add_arc",
    "polyline": "sketch_add_polyline",
    "bspline": "sketch_add_bspline",
    "constraint": "sketch_add_constraint",
    "extrude": "extrude_sketch",
    "pad": "pad_sketch",
    "pocket": "pocket_sketch",
    "revolve": "revolve_sketch",
    "loft": "make_loft",
    "export_step": "export_step",
    "export_stl": "export_stl",
    "save": "save_fcstd",
}

CAD_API_METHODS = frozenset(CAD_TO_TOOL)
CAD_API_VERSION = "1.1"
