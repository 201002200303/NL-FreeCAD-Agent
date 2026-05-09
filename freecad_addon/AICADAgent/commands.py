# commands.py — FreeCAD command classes

import FreeCAD
import FreeCADGui


class AICAD_OpenPanel:
    """Command to open the AI CAD Agent panel."""

    def GetResources(self):
        return {
            "MenuText": "AI CAD Panel",
            "ToolTip": "Open the AI CAD Agent control panel",
            # "Pixmap": path_to_icon  # TODO: add icon
        }

    def Activated(self):
        from AICADAgent.panel import show_panel
        show_panel()

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None
