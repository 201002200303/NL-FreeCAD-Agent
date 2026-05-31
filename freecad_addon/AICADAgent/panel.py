# panel.py — AI CAD Agent control panel (V0.7 closed-loop)

from PySide import QtCore, QtGui

import FreeCAD
import FreeCADGui

from AICADAgent.agent_runner import AgentRunner
from AICADAgent.debug_settings import (
    is_debug_mode,
    set_debug_mode,
    get_debug_sessions_dir,
    resolve_debug_open_path,
)


class AICADPanel(QtGui.QDockWidget):
    """Dockable panel for closed-loop natural language CAD modeling."""

    def __init__(self, parent=None):
        super().__init__("AI CAD Agent", parent)

        self.setObjectName("AICADPanel")
        self.setMinimumWidth(350)

        self._runner = AgentRunner(self)
        self._runner.log_message.connect(self._log)
        self._runner.plan_generated.connect(self._on_plan_generated)
        self._runner.execution_finished.connect(self._on_execution_finished)
        self._runner.error_occurred.connect(self._on_error)

        main_widget = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(main_widget)

        # Input
        layout.addWidget(QtGui.QLabel("建模需求 (Modeling Request):"))
        self.input_edit = QtGui.QTextEdit()
        self.input_edit.setPlaceholderText(
            "用自然语言描述建模需求...\n"
            "例如: 创建一个台灯模型"
        )
        self.input_edit.setMaximumHeight(120)
        layout.addWidget(self.input_edit)

        # Plan button
        self.start_plan_btn = QtGui.QPushButton("生成计划 (逐步执行)")
        self.start_plan_btn.clicked.connect(self._on_start_plan)
        layout.addWidget(self.start_plan_btn)

        # Execution buttons row
        exec_layout = QtGui.QHBoxLayout()
        self.step_btn = QtGui.QPushButton("单步执行")
        self.step_btn.clicked.connect(self._on_step)
        self.step_btn.setEnabled(False)
        exec_layout.addWidget(self.step_btn)

        self.auto_btn = QtGui.QPushButton("自动执行")
        self.auto_btn.clicked.connect(self._on_auto)
        self.auto_btn.setEnabled(False)
        exec_layout.addWidget(self.auto_btn)

        self.pause_btn = QtGui.QPushButton("暂停")
        self.pause_btn.clicked.connect(self._runner.pause)
        self.pause_btn.setEnabled(False)
        exec_layout.addWidget(self.pause_btn)

        self.stop_btn = QtGui.QPushButton("停止")
        self.stop_btn.clicked.connect(self._runner.stop)
        self.stop_btn.setEnabled(False)
        exec_layout.addWidget(self.stop_btn)
        layout.addLayout(exec_layout)

        # Debug settings
        debug_layout = QtGui.QHBoxLayout()
        self.debug_checkbox = QtGui.QCheckBox("调试模式 (记录每步 LLM 输入/输出)")
        self.debug_checkbox.setChecked(is_debug_mode())
        self.debug_checkbox.toggled.connect(self._on_debug_toggled)
        debug_layout.addWidget(self.debug_checkbox)

        self.open_debug_btn = QtGui.QPushButton("打开调试目录")
        self.open_debug_btn.clicked.connect(self._on_open_debug_dir)
        debug_layout.addWidget(self.open_debug_btn)
        layout.addLayout(debug_layout)

        # Log output
        layout.addWidget(QtGui.QLabel("执行轨迹 (Execution Log):"))
        self.log_edit = QtGui.QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText("高层计划和执行轨迹将显示在这里...")
        layout.addWidget(self.log_edit)

        self.setWidget(main_widget)

    def _on_start_plan(self):
        user_input = self.input_edit.toPlainText().strip()
        if not user_input:
            self._log("错误: 请输入建模需求。")
            return

        self._runner.set_debug_mode(self.debug_checkbox.isChecked())
        if self.debug_checkbox.isChecked():
            self._log(f"[调试] 已开启，日志将写入: {get_debug_sessions_dir()}")

        self._set_exec_buttons(enabled=False)
        self.start_plan_btn.setEnabled(False)
        self._runner.start_plan(user_input)

    def _on_plan_generated(self, result: dict):
        self.start_plan_btn.setEnabled(True)
        self.step_btn.setEnabled(True)
        self.auto_btn.setEnabled(True)
        self._log("\n点击 [单步执行] 或 [自动执行] 开始建模...")

    def _on_step(self):
        self._runner.set_debug_mode(self.debug_checkbox.isChecked())
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self._runner.run_step()

    def _on_auto(self):
        self._runner.set_debug_mode(self.debug_checkbox.isChecked())
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.auto_btn.setEnabled(False)
        self.step_btn.setEnabled(False)
        self._runner.run_auto()

    def _on_execution_finished(self, success: bool, message: str):
        self._set_exec_buttons(enabled=False)
        self.step_btn.setEnabled(True)
        self.auto_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        status = "成功" if success else "结束"
        self._log(f"\n=== 执行{status}: {message} ===")

    def _on_error(self, message: str):
        self._log(f"错误: {message}")
        self.start_plan_btn.setEnabled(True)
        self._set_exec_buttons(enabled=False)

    def _set_exec_buttons(self, enabled: bool):
        self.step_btn.setEnabled(enabled)
        self.auto_btn.setEnabled(enabled)

    def _on_debug_toggled(self, checked: bool):
        set_debug_mode(checked)
        self._runner.set_debug_mode(checked)
        state = "开启" if checked else "关闭"
        self._log(f"[调试] 调试模式已{state}")

    def _on_open_debug_dir(self):
        import os
        import subprocess
        path = resolve_debug_open_path(self._runner.debug_session_path)
        os.makedirs(path, exist_ok=True)
        if os.name == "nt":
            os.startfile(path)
        elif hasattr(subprocess, "run"):
            subprocess.run(["xdg-open", path], check=False)
        self._log(f"[调试] 已打开目录: {path}")

    def _log(self, text: str):
        self.log_edit.append(text)
        scrollbar = self.log_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


_panel_instance = None


def show_panel():
    """Create or show the AI CAD Agent panel in FreeCAD."""
    global _panel_instance
    mw = FreeCADGui.getMainWindow()

    if _panel_instance is None:
        _panel_instance = AICADPanel(mw)
        mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, _panel_instance)
    else:
        _panel_instance.show()
        _panel_instance.raise_()
