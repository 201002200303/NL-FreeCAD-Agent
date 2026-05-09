# executor.py — CAD Tool executor that operates on the active FreeCAD document

import FreeCAD
import Part


class CadToolExecutor:
    """Executes a modeling plan step-by-step on the active FreeCAD document.

    Each method wraps FreeCAD API calls with transaction management:
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
                # Stop on first error
                break
        return results

    def execute_step(self, step: dict) -> dict:
        """Execute a single plan step. Dispatches to the correct tool method."""
        tool = step.get("tool", "")
        args = step.get("args", {})
        step_id = step.get("step_id", "?")

        method = getattr(self, tool, None)
        if method is None:
            return {
                "step_id": step_id,
                "status": "error",
                "message": f"Unknown tool: {tool}",
            }

        try:
            self._begin(f"{step_id}: {tool}")
            result = method(**args)
            result["step_id"] = step_id
            result["status"] = "success"
            self._commit()
            return result
        except Exception as e:
            self._rollback()
            return {
                "step_id": step_id,
                "status": "error",
                "tool": tool,
                "message": str(e),
            }

    # ── Primitive tools ──────────────────────────────────────────────

    def create_box(self, name="Box", length=10, width=10, height=10, unit="mm"):
        """Create a Part::Box in the active document."""
        box = self.doc.addObject("Part::Box", name)
        box.Length = length
        box.Width = width
        box.Height = height
        box.Label = name
        return {
            "tool": "create_box",
            "object": box.Name,
            "label": box.Label,
            "type": "Part::Box",
        }

    def create_cylinder(self, name="Cylinder", radius=10, height=20, unit="mm"):
        """Create a Part::Cylinder in the active document."""
        cyl = self.doc.addObject("Part::Cylinder", name)
        cyl.Radius = radius
        cyl.Height = height
        cyl.Label = name
        return {
            "tool": "create_cylinder",
            "object": cyl.Name,
            "label": cyl.Label,
            "type": "Part::Cylinder",
        }

    # ── Stub tools (to be implemented) ───────────────────────────────

    def create_sketch(self, name="Sketch", plane="XY"):
        raise NotImplementedError("create_sketch not implemented yet")

    def pad_sketch(self, name="Pad", sketch="", length=10):
        raise NotImplementedError("pad_sketch not implemented yet")

    def cut_center_hole(self, target="", hole_diameter=5, through_all=True):
        raise NotImplementedError("cut_center_hole not implemented yet")

    def cut_corner_holes(self, target="", hole_diameter=5, margin_x=10, margin_y=10, through_all=True):
        raise NotImplementedError("cut_corner_holes not implemented yet")

    def add_fillet(self, target="", radius=1, edge_selector="all"):
        raise NotImplementedError("add_fillet not implemented yet")

    def add_chamfer(self, target="", size=1, edge_selector="all"):
        raise NotImplementedError("add_chamfer not implemented yet")

    def modify_param(self, target="", param="", value=0):
        """Modify a parameter of an existing object."""
        obj = self.doc.getObject(target)
        if obj is None:
            raise ValueError(f"Object not found: {target}")
        if not hasattr(obj, param):
            raise ValueError(f"Object '{target}' has no parameter '{param}'")
        setattr(obj, param, value)
        return {
            "tool": "modify_param",
            "object": target,
            "param": param,
            "value": value,
        }

    def delete_object(self, target=""):
        """Delete an object from the document."""
        obj = self.doc.getObject(target)
        if obj is None:
            raise ValueError(f"Object not found: {target}")
        self.doc.removeObject(target)
        return {
            "tool": "delete_object",
            "object": target,
        }

    def export_step(self, target="", filepath=""):
        raise NotImplementedError("export_step not implemented yet")

    def export_stl(self, target="", filepath="", tolerance=0.1):
        raise NotImplementedError("export_stl not implemented yet")

    def save_fcstd(self, filepath=""):
        self.doc.saveAs(filepath)
        return {
            "tool": "save_fcstd",
            "filepath": filepath,
        }
