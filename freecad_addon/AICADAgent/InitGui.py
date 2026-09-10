# InitGui.py — FreeCAD Workbench registration

import FreeCAD
import FreeCADGui

class AICADAgentWorkbench(FreeCADGui.Workbench):
    """AI CAD Agent Workbench — natural language driven FreeCAD modeling."""

    MenuText = "AI CAD Agent"
    ToolTip = "Natural language driven CAD modeling agent"
    Icon = ""  # Will be set once icon is available

    def Initialize(self):
        from AICADAgent.commands import AICAD_OpenPanel, AICAD_OpenPlayground

        FreeCAD.Gui.addCommand("AICAD_OpenPanel", AICAD_OpenPanel())
        FreeCAD.Gui.addCommand("AICAD_OpenPlayground", AICAD_OpenPlayground())

        self.list_commands = ["AICAD_OpenPanel", "AICAD_OpenPlayground"]
        self.appendToolbar("AI CAD Agent", self.list_commands)
        self.appendMenu("AI CAD Agent", self.list_commands)

    def Activated(self):
        pass

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


# FreeCAD calls this when loading the module
FreeCADGui.addWorkbench(AICADAgentWorkbench())
