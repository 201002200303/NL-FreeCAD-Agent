# executor.py — CAD Tool executor: plan dispatch + transaction management

import FreeCAD

from AICADAgent.cad_tools import TOOL_REGISTRY


class CadToolExecutor:
    """Executes a modeling plan step-by-step on the active FreeCAD document.

    Each step wraps the tool call with transaction management:
    - openTransaction before operations
    - commitTransaction on success
    - abortTransaction on failure
    - doc.recompute() after commit
    """

    def __init__(self, doc=None):
        self.doc = doc or FreeCAD.ActiveDocument
        if self.doc is None:
            raise RuntimeError("No active FreeCAD document")

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

    def execute_step(self, step: dict) -> dict:
        """Execute a single plan step. Looks up the tool in TOOL_REGISTRY."""
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

        try:
            self._begin(f"{step_id}: {tool_name}")
            result = tool_func(self.doc, **args)
            result["step_id"] = step_id
            result["status"] = "success"
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
