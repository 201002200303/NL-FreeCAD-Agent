"""FreeCAD 插件侧 execute_cad_program。

与 agent_service/app/cad_program 规则保持一致（复制，避免跨进程包依赖）。
"""

from AICADAgent.cad_program.runtime import run_cad_program

__all__ = ["run_cad_program"]
