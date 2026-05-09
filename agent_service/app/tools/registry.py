from app.tools.tool_specs import TOOL_SPECS, get_tool_spec, list_tool_names


class ToolRegistry:
    """Central registry for all CAD Tool specifications."""

    def __init__(self):
        self._specs: dict = dict(TOOL_SPECS)

    def get(self, tool_name: str) -> dict | None:
        return self._specs.get(tool_name)

    def list_tools(self) -> list[str]:
        return list(self._specs.keys())

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self._specs

    def validate_args(self, tool_name: str, args: dict) -> list[str]:
        """Validate args against tool spec. Returns list of missing required params."""
        spec = self.get(tool_name)
        if spec is None:
            return [f"Unknown tool: {tool_name}"]
        missing = []
        for param in spec.get("required", []):
            if param not in args or args[param] is None:
                missing.append(param)
        return missing


tool_registry = ToolRegistry()
