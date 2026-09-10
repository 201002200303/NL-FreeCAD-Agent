"""Cad Playground — 你当 LLM：粘贴 cad.* 代码，走 Agent 同通道执行并看模型。"""

from PySide import QtCore, QtGui

import FreeCAD
import FreeCADGui

from AICADAgent.executor import CadToolExecutor


_SAMPLE = """# 与 Agent 的 execute_cad_program 相同规则
cad.delete(["Demo", "Wheel"])
cad.box(name="Demo", size=(40, 25, 20), center=(0, 0, 10))
cad.cylinder(name="Wheel", radius=15, height=8, center=(30, 0, 15), rot_y=90)
"""


class CadPlaygroundPanel(QtGui.QDockWidget):
    def __init__(self, parent=None):
        super(CadPlaygroundPanel, self).__init__("CAD Playground", parent)
        self.setObjectName("CadPlaygroundPanel")
        self.setMinimumWidth(380)
        self._executor = None

        body = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(body)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QtGui.QLabel("CAD Playground")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(title)

        hint = QtGui.QLabel(
            "粘贴受限 cad.* 程序（与 Agent 相同通道）→ 运行 → 在 3D 视图检查。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #4b5563; font-size: 12px;")
        layout.addWidget(hint)

        self.editor = QtGui.QPlainTextEdit()
        self.editor.setPlainText(_SAMPLE)
        # PySide6: setTabStopWidth 已移除
        self.editor.setTabStopDistance(16)
        font = QtGui.QFont("Consolas")
        font.setStyleHint(QtGui.QFont.Monospace)
        font.setPointSize(10)
        self.editor.setFont(font)
        layout.addWidget(self.editor, 1)

        row = QtGui.QHBoxLayout()
        self.run_btn = QtGui.QPushButton("运行")
        self.run_btn.clicked.connect(self._on_run)
        row.addWidget(self.run_btn)
        clear_code = QtGui.QPushButton("清空代码")
        clear_code.clicked.connect(self.editor.clear)
        row.addWidget(clear_code)
        sample_btn = QtGui.QPushButton("示例")
        sample_btn.clicked.connect(lambda: self.editor.setPlainText(_SAMPLE))
        row.addWidget(sample_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self.result = QtGui.QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setMaximumHeight(140)
        self.result.setFont(font)
        self.result.setPlaceholderText("执行结果…")
        layout.addWidget(self.result)

        self.setWidget(body)

    def _get_executor(self):
        if self._executor is None:
            self._executor = CadToolExecutor()
        else:
            # 跟随当前活动文档
            self._executor.doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("Playground")
        return self._executor

    def _on_run(self):
        code = (self.editor.toPlainText() or "").strip()
        if not code:
            self.result.setPlainText("代码为空")
            return
        if FreeCAD.ActiveDocument is None:
            FreeCAD.newDocument("Playground")
        ex = self._get_executor()
        self.run_btn.setEnabled(False)
        self.result.setPlainText("执行中…")
        QtGui.QApplication.processEvents()
        try:
            out = ex.execute_tool_call(
                {
                    "call_id": "playground_1",
                    "tool": "execute_cad_program",
                    "args": {"transaction": "playground", "code": code},
                }
            )
            lines = [
                "status: %s" % out.get("status"),
                "produced: %s" % (out.get("produced_objects") or []),
            ]
            if out.get("message"):
                lines.append("message: %s" % out.get("message"))
            if out.get("error_type"):
                lines.append("error_type: %s" % out.get("error_type"))
            if out.get("failed_line") is not None:
                lines.append("failed_line: %s" % out.get("failed_line"))
            if out.get("state_diff"):
                lines.append("diff: %s" % (out["state_diff"].get("summary") or out["state_diff"]))
            checks = (out.get("checks") or {})
            if checks:
                lines.append("checks: %s" % checks)
            self.result.setPlainText("\n".join(lines))
            try:
                FreeCADGui.SendMsgToActiveView("ViewFit")
            except Exception:
                pass
        except Exception as exc:
            self.result.setPlainText("exception: %s" % exc)
        finally:
            self.run_btn.setEnabled(True)


def show_playground():
    mw = FreeCADGui.getMainWindow()
    existing = mw.findChild(QtGui.QDockWidget, "CadPlaygroundPanel")
    if existing:
        existing.setVisible(True)
        existing.raise_()
        return existing
    panel = CadPlaygroundPanel(mw)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, panel)
    panel.setVisible(True)
    return panel
