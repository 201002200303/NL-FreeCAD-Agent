# commands.py — FreeCAD command classes

import FreeCAD
import FreeCADGui


class AICAD_OpenPanel:
    """Command to open the AI CAD Agent panel."""

    def GetResources(self):
        return {
            "MenuText": "AI CAD Panel",
            "ToolTip": "Open the AI CAD Agent control panel",
        }

    def Activated(self):
        from AICADAgent.panel import show_panel

        show_panel()

    def IsActive(self):
        return True


class AICAD_OpenPlayground:
    """Paste cad.* code and run via the same channel as the Agent."""

    def GetResources(self):
        return {
            "MenuText": "CAD Playground",
            "ToolTip": "Paste cad.* code (like the LLM) and execute in FreeCAD",
        }

    def Activated(self):
        try:
            from AICADAgent.playground import show_playground

            show_playground()
        except Exception as exc:
            FreeCAD.Console.PrintError("CAD Playground failed: %s\n" % exc)
            import traceback

            FreeCAD.Console.PrintError(traceback.format_exc() + "\n")

    def IsActive(self):
        return True
