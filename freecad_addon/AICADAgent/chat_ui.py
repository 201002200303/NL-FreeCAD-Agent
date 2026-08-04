"""Cursor-style chat primitives for the FreeCAD dock panel.

- TranscriptView: one scroll surface for user / assistant / thinking
- ComposerBar: input + send/stop (no separate control strip)
"""

from __future__ import annotations

from PySide import QtCore, QtGui


def _esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )


class TranscriptView(QtGui.QTextBrowser):
    """Read-only conversation surface. Thinking uses quieter typography."""

    def __init__(self, parent=None):
        super(TranscriptView, self).__init__(parent)
        self.setObjectName("ChatTranscript")
        self.setOpenExternalLinks(False)
        self.setReadOnly(True)
        self.document().setDefaultStyleSheet(
            """
            body { font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; font-size: 13px; color: #1f2937; }
            .block { margin: 10px 0 12px 0; }
            .role { font-size: 11px; font-weight: 700; letter-spacing: 0.02em; margin-bottom: 2px; }
            .role-user { color: #2563eb; }
            .role-assistant { color: #111827; }
            .role-system { color: #b45309; }
            .role-thinking { color: #9ca3af; font-weight: 600; }
            .body { line-height: 1.45; }
            .body-thinking {
                color: #6b7280;
                font-size: 12px;
                font-family: Consolas, 'Courier New', monospace;
                line-height: 1.35;
                padding-left: 8px;
                border-left: 2px solid #e5e7eb;
            }
            .meta { color: #9ca3af; font-size: 11px; margin-top: 4px; }
            """
        )
        self.setPlaceholderText(
            "和 Agent 对话来建模。\n"
            "运行中也可继续输入——消息会排队，当前轮结束或点停止后再发。"
        )

    def clear(self):
        super(TranscriptView, self).clear()

    def append_event(self, kind: str, text: str, meta: dict | None = None):
        text = (text or "").strip()
        if not text:
            return
        kind = (kind or "system").lower()
        if kind == "user":
            self._append_html("你", text, "user", thinking=False)
        elif kind == "assistant":
            self._append_html("Agent", text, "assistant", thinking=False)
        elif kind == "thinking":
            label = (meta or {}).get("label") or "thinking"
            self._append_html(label, text, "thinking", thinking=True)
        else:
            self._append_html("系统", text, "system", thinking=False)

    def _append_html(self, role: str, text: str, role_class: str, *, thinking: bool):
        body_class = "body-thinking" if thinking else "body"
        html = (
            f'<div class="block">'
            f'<div class="role role-{role_class}">{_esc(role)}</div>'
            f'<div class="{body_class}">{_esc(text)}</div>'
            f"</div>"
        )
        self.append(html)
        self.moveCursor(QtGui.QTextCursor.End)


class ComposerBar(QtGui.QWidget):
    """Bottom composer: multiline input + send/stop, Cursor-like."""

    send_requested = QtCore.Signal(str)
    stop_requested = QtCore.Signal()

    def __init__(self, parent=None):
        super(ComposerBar, self).__init__(parent)
        self.setObjectName("ComposerBar")
        self._busy = False

        layout = QtGui.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.input = QtGui.QTextEdit()
        self.input.setObjectName("ComposerInput")
        self.input.setPlaceholderText("描述需求或继续改模型…  Ctrl+Enter 发送")
        self.input.setMaximumHeight(100)
        self.input.setMinimumHeight(56)
        layout.addWidget(self.input)

        row = QtGui.QHBoxLayout()
        row.setSpacing(8)
        self.hint = QtGui.QLabel("Ctrl+Enter 发送 · 忙时消息会排队")
        self.hint.setObjectName("ComposerHint")
        row.addWidget(self.hint, 1)

        self.stop_btn = QtGui.QPushButton("停止")
        self.stop_btn.setObjectName("StopButton")
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        row.addWidget(self.stop_btn)

        self.send_btn = QtGui.QPushButton("发送")
        self.send_btn.setObjectName("SendButton")
        self.send_btn.clicked.connect(self._emit_send)
        row.addWidget(self.send_btn)
        layout.addLayout(row)

        self.input.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QtCore.QEvent.KeyPress:
            if (
                event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter)
                and event.modifiers() & QtCore.Qt.ControlModifier
            ):
                self._emit_send()
                return True
        return super(ComposerBar, self).eventFilter(obj, event)

    def _emit_send(self):
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.send_requested.emit(text)

    def set_busy(self, busy: bool):
        self._busy = bool(busy)
        self.stop_btn.setVisible(self._busy)
        # 忙时仍可发送（入队）；停止键出现表示可打断当前轮
        self.send_btn.setText("排队" if self._busy else "发送")
        self.hint.setText(
            "已排队将在当前轮结束后发送 · 点停止可提前结束"
            if self._busy
            else "Ctrl+Enter 发送 · 忙时消息会排队"
        )

    def focus_input(self):
        self.input.setFocus()
