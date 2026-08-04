# panel.py — Cursor-style CAD chat dock (transcript + composer)

from PySide import QtCore, QtGui

import FreeCADGui

from AICADAgent.agent_runner import AgentRunner
from AICADAgent.chat_ui import ComposerBar, TranscriptView
from AICADAgent.debug_settings import (
    is_debug_mode,
    set_debug_mode,
    get_debug_sessions_dir,
)


class AICADPanel(QtGui.QDockWidget):
    """One chat surface: transcript + composer. Log is a debug drawer."""

    def __init__(self, parent=None):
        super(AICADPanel, self).__init__("AI CAD Agent", parent)
        self.setObjectName("AICADPanel")
        self.setMinimumWidth(400)

        self._runner = AgentRunner(self)
        self._wire_runner()

        body = QtGui.QWidget()
        body.setObjectName("AICADPanelBody")
        root = QtGui.QVBoxLayout(body)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self._build_header(root)
        self.transcript = TranscriptView()
        root.addWidget(self.transcript, 1)

        self.composer = ComposerBar()
        self.composer.send_requested.connect(self._on_send)
        self.composer.stop_requested.connect(self._runner.stop)
        root.addWidget(self.composer)

        self._build_log_drawer(root)

        self.setWidget(body)
        self._apply_style()
        self._set_status("空闲")
        QtCore.QTimer.singleShot(0, self._runner.fetch_capabilities)

    def _wire_runner(self):
        self._runner.chat_event.connect(self._on_chat_event)
        self._runner.busy_changed.connect(self._on_busy)
        self._runner.error_occurred.connect(self._on_error)
        self._runner.execution_finished.connect(self._on_finished)
        self._runner.log_message.connect(self._log)
        if hasattr(self._runner, "session_restored"):
            self._runner.session_restored.connect(self._on_session_restored)
        if hasattr(self._runner, "paused_state_changed"):
            self._runner.paused_state_changed.connect(self._on_paused)
        # legacy signals unused by this UI
        self._runner.plan_generated.connect(lambda *_: None)
        self._runner.step_completed.connect(lambda *_: None)
        self._runner.chat_reply.connect(self._on_chat_reply_meta)

    # ── layout ────────────────────────────────────────────────────

    def _build_header(self, layout):
        title = QtGui.QLabel("AI CAD Agent")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        self.status_value = QtGui.QLabel("空闲")
        self.status_value.setObjectName("StatusLine")
        self.status_value.setWordWrap(True)
        layout.addWidget(self.status_value)

        meta = QtGui.QHBoxLayout()
        self.session_value = QtGui.QLabel("Session: -")
        self.session_value.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.ctx_value = QtGui.QLabel("")
        meta.addWidget(self.session_value)
        meta.addStretch(1)
        meta.addWidget(self.ctx_value)
        layout.addLayout(meta)

        opts = QtGui.QHBoxLayout()
        self.plan_mode_cb = QtGui.QCheckBox("Plan")
        self.plan_mode_cb.setChecked(True)
        self.plan_mode_cb.setToolTip("维护 soft todo；也可在对话里说「直接做」")
        self.plan_mode_cb.toggled.connect(self._runner.set_plan_mode)
        opts.addWidget(self.plan_mode_cb)

        self.vision_cb = QtGui.QCheckBox("视觉")
        self.vision_cb.setChecked(False)
        self.vision_cb.setToolTip("需服务端 VISION_ENABLED + VISION_MODEL")
        self.vision_cb.toggled.connect(self._runner.set_vision_enabled)
        opts.addWidget(self.vision_cb)

        self.debug_checkbox = QtGui.QCheckBox("Debug")
        self.debug_checkbox.setChecked(is_debug_mode())
        self.debug_checkbox.toggled.connect(self._on_debug_toggled)
        opts.addWidget(self.debug_checkbox)
        opts.addStretch(1)

        self.compress_btn = QtGui.QToolButton()
        self.compress_btn.setText("压缩")
        self.compress_btn.clicked.connect(self._runner.compress_chat_context)
        opts.addWidget(self.compress_btn)

        self.new_chat_btn = QtGui.QToolButton()
        self.new_chat_btn.setText("新对话")
        self.new_chat_btn.clicked.connect(self._on_new_chat)
        opts.addWidget(self.new_chat_btn)
        layout.addLayout(opts)

    def _build_log_drawer(self, layout):
        self.log_toggle = QtGui.QToolButton()
        self.log_toggle.setText("日志 ▸")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setChecked(False)
        self.log_toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        self.log_toggle.toggled.connect(self._on_log_toggled)
        layout.addWidget(self.log_toggle)

        self.log_edit = QtGui.QTextEdit()
        self.log_edit.setObjectName("DebugLog")
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumHeight(140)
        self.log_edit.setVisible(False)
        layout.addWidget(self.log_edit)

    # ── actions ───────────────────────────────────────────────────

    def _on_send(self, text):
        self._runner.set_debug_mode(self.debug_checkbox.isChecked())
        self._runner.set_plan_mode(self.plan_mode_cb.isChecked())
        self._runner.set_vision_enabled(self.vision_cb.isChecked())
        if getattr(self._runner, "_chat_busy", False):
            self._set_status("已排队 — 当前轮结束后发送")
        else:
            self._set_status("思考中…")
        self._runner.send_chat(text)

    def _on_new_chat(self):
        self._runner.new_chat()
        self.transcript.clear()
        self.session_value.setText("Session: -")
        self.ctx_value.setText("")
        self._set_status("新对话")
        self.composer.focus_input()

    def _on_debug_toggled(self, checked):
        set_debug_mode(checked)
        self._runner.set_debug_mode(checked)
        if checked:
            self._log(f"[调试] 目录: {get_debug_sessions_dir()}")
            self.log_toggle.setChecked(True)

    def _on_log_toggled(self, open_):
        self.log_edit.setVisible(open_)
        self.log_toggle.setText("日志 ▾" if open_ else "日志 ▸")

    # ── runner → UI ───────────────────────────────────────────────

    def _on_chat_event(self, event):
        kind = (event or {}).get("kind") or "system"
        text = (event or {}).get("text") or ""
        meta = (event or {}).get("meta") or {}
        self.transcript.append_event(kind, text, meta)

    def _on_chat_reply_meta(self, result):
        """Update session chrome from ChatResponse; content already via chat_event."""
        sid = result.get("session_id") or "-"
        self.session_value.setText(f"Session: {sid}")
        chars = result.get("context_chars", 0)
        turns = result.get("turn_count", 0)
        if chars or turns:
            self.ctx_value.setText(f"{turns} 回合 · {chars} 字")

        status = result.get("status", "")
        if status == "queued":
            self._set_status("已排队")
        elif status == "awaiting_tools":
            n = len(result.get("tool_calls") or [])
            self._set_status(f"执行工具（{n}）…")
        elif status == "awaiting_user":
            self._set_status("等待你的消息")
        elif status == "done":
            self._set_status("本轮完成")
        elif status == "error":
            self._set_status("出错")

    def _on_busy(self, busy):
        self.composer.set_busy(busy)
        if busy:
            self._set_status("运行中…")

    def _on_error(self, err):
        self.transcript.append_event("system", f"错误: {err}")
        self._set_status("错误")
        self._log(f"错误: {err}")
        self.composer.set_busy(False)

    def _on_finished(self, ok, message):
        self.composer.set_busy(False)
        self._set_status("完成" if ok else f"结束: {message}")

    def _on_session_restored(self, result):
        sid = result.get("session_id", "-")
        self.session_value.setText(f"Session: {sid}")
        self.transcript.append_event("system", f"会话已恢复: {sid}")
        self._set_status("已恢复")

    def _on_paused(self, paused):
        self._set_status("已暂停" if paused else "运行中")

    def _log(self, msg):
        self.log_edit.append(msg)

    def _set_status(self, text):
        self.status_value.setText(text)

    def _apply_style(self):
        self.setStyleSheet(
            """
            #AICADPanelBody { background: #f4f5f7; color: #20242a; }
            #PanelTitle { font-size: 16px; font-weight: 700; color: #111827; }
            #StatusLine { color: #4b5563; font-size: 12px; }
            #ChatTranscript {
                border: 1px solid #e5e7eb; border-radius: 8px;
                background: #ffffff; padding: 8px;
            }
            #ComposerBar { background: transparent; }
            #ComposerInput {
                border: 1px solid #d1d5db; border-radius: 8px;
                background: #ffffff; padding: 6px;
            }
            #ComposerHint { color: #9ca3af; font-size: 11px; }
            #SendButton {
                min-width: 72px; min-height: 28px;
                background: #2563eb; color: white; border: none;
                border-radius: 6px; font-weight: 600; padding: 4px 14px;
            }
            #SendButton:hover { background: #1d4ed8; }
            #StopButton {
                min-width: 64px; min-height: 28px;
                background: #ffffff; color: #b91c1c;
                border: 1px solid #fca5a5; border-radius: 6px; padding: 4px 12px;
            }
            #StopButton:hover { background: #fef2f2; }
            #DebugLog {
                border: 1px solid #e5e7eb; border-radius: 6px;
                background: #111827; color: #e5e7eb; font-family: Consolas, monospace;
                font-size: 11px;
            }
            QToolButton {
                border: 1px solid #e5e7eb; border-radius: 4px;
                background: #ffffff; padding: 3px 8px; color: #374151;
            }
            QToolButton:hover { background: #f3f4f6; }
            QToolButton:checked { background: #eff6ff; border-color: #93c5fd; }
            QCheckBox { color: #374151; spacing: 4px; }
            """
        )


def show_panel():
    mw = FreeCADGui.getMainWindow()
    existing = mw.findChild(QtGui.QDockWidget, "AICADPanel")
    if existing:
        # 布局大改后强制重建，避免旧控件残留
        mw.removeDockWidget(existing)
        existing.deleteLater()
    panel = AICADPanel(mw)
    mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, panel)
    panel.setVisible(True)
    return panel
