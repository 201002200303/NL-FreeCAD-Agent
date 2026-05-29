# CAD Tool Registry
# Maps tool names to their implementation functions.
# Each tool function has signature: func(doc, **args) -> dict

from AICADAgent.cad_tools.primitive_tools import create_box, create_cylinder
from AICADAgent.cad_tools.modify_tools import modify_param, delete_object
from AICADAgent.cad_tools.export_tools import save_fcstd

TOOL_REGISTRY: dict = {
    "create_box": create_box,
    "create_cylinder": create_cylinder,
    "modify_param": modify_param,
    "delete_object": delete_object,
    "save_fcstd": save_fcstd,
}


def get_tool(tool_name: str):
    return TOOL_REGISTRY.get(tool_name)


def list_tool_names() -> list[str]:
    return list(TOOL_REGISTRY.keys())
