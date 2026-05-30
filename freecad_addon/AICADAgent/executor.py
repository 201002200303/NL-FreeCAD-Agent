# executor.py — CAD Tool executor: plan dispatch + transaction management

import FreeCAD

from AICADAgent.cad_tools import TOOL_REGISTRY

# args 中引用文档对象名的字段
_NAME_REF_FIELDS = frozenset({
    "target", "base", "tool", "sketch", "body",
    "part", "part1", "part2", "assembly",
    "profile", "path",
})


class CadToolExecutor:
    """Executes a modeling plan step-by-step on the active FreeCAD document.

    Each step wraps the tool call with transaction management:
    - openTransaction before operations
    - commitTransaction on success
    - abortTransaction on failure
    - doc.recompute() after commit

    Maintains a name_map so that later steps referencing a replaced object
    (e.g. "Base" after fillet produced "Base_Fillet") are auto-resolved.
    """

    def __init__(self, doc=None):
        self.doc = doc or FreeCAD.ActiveDocument
        if self.doc is None:
            raise RuntimeError("No active FreeCAD document")
        self.name_map: dict[str, str] = {}

    def _resolve(self, name: str) -> str:
        """Follow the name chain to the latest object name."""
        visited = set()
        while name in self.name_map and name not in visited:
            visited.add(name)
            name = self.name_map[name]
        return name

    def _rewrite_args(self, args: dict) -> dict:
        """Return a copy of args with object-name references resolved."""
        rewritten = {}
        for key, value in args.items():
            if key in _NAME_REF_FIELDS and isinstance(value, str):
                rewritten[key] = self._resolve(value)
            else:
                rewritten[key] = value
        return rewritten

    # ── Transaction helpers ──────────────────────────────────────────

    def _begin(self, name: str = "AI CAD Tool Step"):
        self.doc.openTransaction(name)

    def _commit(self):
        self.doc.commitTransaction()
        self.doc.recompute()

    def _rollback(self):
        self.doc.abortTransaction()

    # ── Plan execution ───────────────────────────────────────────────

    def execute_plan(self, plan: list[dict]) -> list[dict]:
        """Execute an entire plan, returning results per step."""
        results = []
        for step in plan:
            result = self.execute_step(step)
            results.append(result)
            if result.get("status") == "error":
                break
        return results

    def execute_tool_call(self, tool_call: dict) -> dict:
        """Execute a single tool call with enhanced result structure.

        This is the new V0.7 API for the closed-loop architecture.
        Returns a unified result dict with call_id, produced_objects,
        source_objects, name_map_update, etc.
        """
        call_id = tool_call.get("call_id", "unknown")
        tool_name = tool_call.get("tool", "")
        args = tool_call.get("args", {})

        tool_func = TOOL_REGISTRY.get(tool_name)
        if tool_func is None:
            return {
                "call_id": call_id,
                "status": "error",
                "tool": tool_name,
                "args": args,
                "resolved_args": args,
                "produced_objects": [],
                "source_objects": [],
                "name_map_update": {},
                "message": f"Unknown tool: {tool_name}",
            }

        resolved_args = self._rewrite_args(args)

        try:
            self._begin(f"{call_id}: {tool_name}")
            result = tool_func(self.doc, **resolved_args)
            result["call_id"] = call_id
            result["status"] = "success"

            # Track name chain
            source = result.get("source")
            obj_name = result.get("object")
            name_map_update = {}
            if source and obj_name and source != obj_name:
                self.name_map[source] = obj_name
                name_map_update = {source: obj_name}

            # Build enhanced result
            produced = []
            if obj_name:
                produced.append(obj_name)

            source_objects = []
            if source:
                source_objects.append(source)

            self._commit()

            return {
                "call_id": call_id,
                "status": "success",
                "tool": tool_name,
                "args": args,
                "resolved_args": resolved_args,
                "produced_objects": produced,
                "source_objects": source_objects,
                "name_map_update": name_map_update,
                "message": None,
                **{k: v for k, v in result.items() if k not in [
                    "call_id", "status", "tool", "args", "resolved_args",
                    "produced_objects", "source_objects", "name_map_update", "message"
                ]}
            }
        except Exception as e:
            self._rollback()
            return {
                "call_id": call_id,
                "status": "error",
                "tool": tool_name,
                "args": args,
                "resolved_args": resolved_args,
                "produced_objects": [],
                "source_objects": [],
                "name_map_update": {},
                "message": str(e),
            }

    def execute_step(self, step: dict) -> dict:
        """Execute a single plan step. Looks up the tool in TOOL_REGISTRY.

        Legacy API for backward compatibility. Use execute_tool_call() for V0.7+.
        """
        tool_name = step.get("tool", "")
        args = step.get("args", {})
        step_id = step.get("step_id", "?")

        tool_func = TOOL_REGISTRY.get(tool_name)
        if tool_func is None:
            return {
                "step_id": step_id,
                "status": "error",
                "message": f"Unknown tool: {tool_name}",
            }

        resolved_args = self._rewrite_args(args)

        try:
            self._begin(f"{step_id}: {tool_name}")
            result = tool_func(self.doc, **resolved_args)
            result["step_id"] = step_id
            result["status"] = "success"

            # Track name chain
            source = result.get("source")
            obj_name = result.get("object")
            if source and obj_name and source != obj_name:
                self.name_map[source] = obj_name

            self._commit()
            return result
        except Exception as e:
            self._rollback()
            return {
                "step_id": step_id,
                "status": "error",
                "tool": tool_name,
                "message": str(e),
            }
