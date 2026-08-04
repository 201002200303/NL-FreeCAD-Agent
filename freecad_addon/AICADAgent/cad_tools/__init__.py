# CAD Tool Registry

from AICADAgent.cad_tools.primitive_tools import (
    create_box, create_cylinder, create_sphere, create_cone, create_torus,
)
from AICADAgent.cad_tools.boolean_tools import boolean_fuse, boolean_cut, boolean_common
from AICADAgent.cad_tools.feature_tools import add_fillet, add_chamfer, cut_hole
from AICADAgent.cad_tools.transform_tools import (
    move, rotate, scale, copy_object, polar_pattern, linear_pattern,
)
from AICADAgent.cad_tools.placement_tools import align_objects, place_relative, distribute_along
from AICADAgent.cad_tools.modify_tools import modify_param, delete_object, set_placement
from AICADAgent.cad_tools.export_tools import save_fcstd, export_step, export_stl
from AICADAgent.cad_tools.query_tools import (
    list_topology, summarize_document, get_object_detail,
    measure_gap, compare_orientation,
)
from AICADAgent.cad_tools.sketch_tools import (
    create_body, create_sketch, create_sketch_on_face,
    sketch_add_line, sketch_add_rect, sketch_add_circle,
    sketch_add_arc, sketch_add_polyline, sketch_add_bspline,
    sketch_add_constraint,
)
from AICADAgent.cad_tools.partdesign_tools import (
    pad_sketch, pocket_sketch, pad_to_face, revolve_sketch, extrude_sketch,
)
from AICADAgent.cad_tools.surface_tools import make_loft, make_sweep, make_revolve
from AICADAgent.cad_tools.assembly_tools import (
    create_assembly, add_to_assembly, mate_planes, mate_coaxial,
)

TOOL_REGISTRY: dict = {
    "create_box": create_box,
    "create_cylinder": create_cylinder,
    "create_sphere": create_sphere,
    "create_cone": create_cone,
    "create_torus": create_torus,
    "boolean_fuse": boolean_fuse,
    "boolean_cut": boolean_cut,
    "boolean_common": boolean_common,
    "add_fillet": add_fillet,
    "add_chamfer": add_chamfer,
    "cut_hole": cut_hole,
    "set_placement": set_placement,
    "move": move,
    "rotate": rotate,
    "scale": scale,
    "copy_object": copy_object,
    "polar_pattern": polar_pattern,
    "linear_pattern": linear_pattern,
    "align_objects": align_objects,
    "place_relative": place_relative,
    "distribute_along": distribute_along,
    "modify_param": modify_param,
    "delete_object": delete_object,
    "save_fcstd": save_fcstd,
    "export_step": export_step,
    "export_stl": export_stl,
    "summarize_document": summarize_document,
    "get_object_detail": get_object_detail,
    "measure_gap": measure_gap,
    "compare_orientation": compare_orientation,
    "list_topology": list_topology,
    "create_body": create_body,
    "create_sketch": create_sketch,
    "create_sketch_on_face": create_sketch_on_face,
    "sketch_add_line": sketch_add_line,
    "sketch_add_rect": sketch_add_rect,
    "sketch_add_circle": sketch_add_circle,
    "sketch_add_arc": sketch_add_arc,
    "sketch_add_polyline": sketch_add_polyline,
    "sketch_add_bspline": sketch_add_bspline,
    "sketch_add_constraint": sketch_add_constraint,
    "pad_sketch": pad_sketch,
    "pocket_sketch": pocket_sketch,
    "pad_to_face": pad_to_face,
    "revolve_sketch": revolve_sketch,
    "extrude_sketch": extrude_sketch,
    "make_loft": make_loft,
    "make_sweep": make_sweep,
    "make_revolve": make_revolve,
    "create_assembly": create_assembly,
    "add_to_assembly": add_to_assembly,
    "mate_planes": mate_planes,
    "mate_coaxial": mate_coaxial,
}


def get_tool(tool_name: str):
    return TOOL_REGISTRY.get(tool_name)


def list_tool_names() -> list[str]:
    return list(TOOL_REGISTRY.keys())
