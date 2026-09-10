"""Canonical model-visible CAD operation catalog.

Packaged copy of agent_service/app/cad_program/manifest.py.  Conformance tests
require the copies to match because Agent and FreeCAD run in separate installs.
"""

CAD_TO_TOOL = {
    "box": "create_box",
    "cylinder": "create_cylinder",
    "sphere": "create_sphere",
    "cone": "create_cone",
    "torus": "create_torus",
    "wedge": "create_wedge",  # TEST
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
    "sweep": "make_sweep",  # TEST
    "export_step": "export_step",
    "export_stl": "export_stl",
    "save": "save_fcstd",
}

# 标注：已入库但人工验收中，整测脚本见 agent_service/data/_tool_test_bench.cad.py
CAD_API_TEST = frozenset({"sweep", "wedge"})

CAD_API_METHODS = frozenset(CAD_TO_TOOL)
CAD_API_VERSION = "1.1-test"
