# panel.py - AI CAD Agent control panel (V0.8 query-driven loop)

from PySide import QtCore, QtGui

import FreeCADGui

from AICADAgent.agent_runner import AgentRunner
from AICADAgent.debug_settings import (
    is_debug_mode,
    set_debug_mode,
    get_debug_sessions_dir,
    resolve_debug_open_path,
)


class AICADPanel(QtGui.QDockWidget):
    """Dockable panel for query-driven closed-loop CAD modeling."""

    def __init__(self, parent=None):
        super().__init__("AI CAD Agent", parent)

        self.setObjectName("AICADPanel")
        self.setMinimumWidth(430)
        self._phase_items = {}
        self._phase_order = []

        self._runner = AgentRunner(self)
        self._runner.log_message.connect(self._log)
        self._runner.plan_generated.connect(self._on_plan_generated)
        self._runner.step_completed.connect(self._on_step_completed)
        self._runner.phase_changed.connect(self._on_phase_changed)
        if hasattr(self._runner, "evaluation_completed"):
            self._runner.evaluation_completed.connect(self._on_evaluation_completed)
        self._runner.execution_finished.connect(self._on_execution_finished)
        self._runner.error_occurred.connect(self._on_error)

        main_widget = QtGui.QWidget()
        main_widget.setObjectName("AICADPanelBody")
        layout = QtGui.QVBoxLayout(main_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._build_header(layout)
        self._build_request_box(layout)
        self._build_status_box(layout)
        self._build_controls(layout)
        self._build_tabs(layout)

        self.setWidget(main_widget)
        self._apply_style()
        self._set_status("空闲")

    def _build_header(self, layout):
        title = QtGui.QLabel("AI CAD Agent")
        title.setObjectName("PanelTitle")
        subtitle = QtGui.QLabel("Plan -> Query -> Act -> Verify")
        subtitle.setObjectName("PanelSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

    def _build_request_box(self, layout):
        box = QtGui.QGroupBox("建模需求")
        box_layout = QtGui.QVBoxLayout(box)
        self.input_edit = QtGui.QTextEdit()
        self.input_edit.setPlaceholderText(
            "用自然语言描述要创建或修改的 CAD 模型。\n"
            "例如：创建一个带支架和轮轴的简化小车，并保证车轮贴合轴端。"
        )
        self.input_edit.setMaximumHeight(115)
        box_layout.addWidget(self.input_edit)

        self.start_plan_btn = QtGui.QPushButton("生成计划")
        self.start_plan_btn.clicked.connect(self._on_start_plan)
        box_layout.addWidget(self.start_plan_btn)
        layout.addWidget(box)

    def _build_status_box(self, layout):
        box = QtGui.QGroupBox("会话状态")
        grid = QtGui.QGridLayout(box)
        grid.setColumnStretch(1, 1)

        self.status_value = self._status_label("-")
        self.session_value = self._status_label("-")
        self.phase_value = self._status_label("-")
        self.step_value = self._status_label("-")

        rows = [
            ("状态", self.status_value),
            ("Session", self.session_value),
            ("当前阶段", self.phase_value),
            ("当前步骤", self.step_value),
        ]
        for row, (label, value) in enumerate(rows):
            grid.addWidget(QtGui.QLabel(label), row, 0)
            grid.addWidget(value, row, 1)

        layout.addWidget(box)

    def _build_controls(self, layout):
        box = QtGui.QGroupBox("执行控制")
        box_layout = QtGui.QVBoxLayout(box)

        row = QtGui.QHBoxLayout()
        self.step_btn = QtGui.QPushButton("单步")
        self.step_btn.clicked.connect(self._on_step)
        self.step_btn.setEnabled(False)
        row.addWidget(self.step_btn)

        self.auto_btn = QtGui.QPushButton("自动")
        self.auto_btn.clicked.connect(self._on_auto)
        self.auto_btn.setEnabled(False)
        row.addWidget(self.auto_btn)

        self.pause_btn = QtGui.QPushButton("暂停")
        self.pause_btn.clicked.connect(self._runner.pause)
        self.pause_btn.setEnabled(False)
        row.addWidget(self.pause_btn)

        self.stop_btn = QtGui.QPushButton("停止")
        self.stop_btn.clicked.connect(self._runner.stop)
        self.stop_btn.setEnabled(False)
        row.addWidget(self.stop_btn)
        box_layout.addLayout(row)

        self.progress_bar = QtGui.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        box_layout.addWidget(self.progress_bar)

        debug_row = QtGui.QHBoxLayout()
        self.debug_checkbox = QtGui.QCheckBox("Debug trace")
        self.debug_checkbox.setChecked(is_debug_mode())
        self.debug_checkbox.toggled.connect(self._on_debug_toggled)
        debug_row.addWidget(self.debug_checkbox)

        self.open_debug_btn = QtGui.QPushButton("打开调试目录")
        self.open_debug_btn.clicked.connect(self._on_open_debug_dir)
        debug_row.addWidget(self.open_debug_btn)
        box_layout.addLayout(debug_row)
        layout.addWidget(box)

    def _build_tabs(self, layout):
        self.tabs = QtGui.QTabWidget()

        self.plan_tree = QtGui.QTreeWidget()
        self.plan_tree.setColumnCount(3)
        self.plan_tree.setHeaderLabels(["阶段", "状态", "目标 / 成功标准"])
        self.plan_tree.setRootIsDecorated(False)
        self.plan_tree.setAlternatingRowColors(True)
        self.plan_tree.setEditTriggers(QtGui.QAbstractItemView.NoEditTriggers)
        self.plan_tree.header().setStretchLastSection(True)
        self.tabs.addTab(self.plan_tree, "计划")

        self.trace_table = QtGui.QTableWidget()
        self.trace_table.setColumnCount(4)
        self.trace_table.setHorizontalHeaderLabels(["类型", "名称", "状态", "摘要"])
        self.trace_table.setEditTriggers(QtGui.QAbstractItemView.NoEditTriggers)
        self.trace_table.setSelectionBehavior(QtGui.QAbstractItemView.SelectRows)
        self.trace_table.setAlternatingRowColors(True)
        self.trace_table.horizontalHeader().setStretchLastSection(True)
        self.tabs.addTab(self.trace_table, "查询 / 验证")

        self.log_edit = QtGui.QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText("Agent 的规划、工具调用和执行日志会显示在这里。")
        self.tabs.addTab(self.log_edit, "日志")

        layout.addWidget(self.tabs, 1)

    def _apply_style(self):
        self.setStyleSheet(
            """
            #AICADPanelBody {
                background: #f6f7f9;
                color: #20242a;
            }
            #PanelTitle {
                font-size: 18px;
                font-weight: 700;
                color: #111827;
            }
            #PanelSubtitle {
                color: #667085;
                margin-bottom: 4px;
            }
            QGroupBox {
                border: 1px solid #d9dde5;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 12px;
                background: #ffffff;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
                color: #344054;
            }
            QTextEdit, QTreeWidget, QTableWidget {
                border: 1px solid #d0d5dd;
                border-radius: 4px;
                background: #ffffff;
                selection-background-color: #dbeafe;
            }
            QPushButton {
                min-height: 26px;
                padding: 4px 10px;
                border: 1px solid #b9c2d0;
                border-radius: 4px;
                background: #ffffff;
            }
            QPushButton:hover {
                background: #eef4ff;
                border-color: #7aa7e8;
            }
            QPushButton:disabled {
                color: #98a2b3;
                background: #f2f4f7;
            }
            QTabWidget::pane {
                border: 1px solid #d0d5dd;
                background: #ffffff;
            }
            QTabBar::tab {
                padding: 6px 10px;
                border: 1px solid #d0d5dd;
                border-bottom: none;
                background: #edf0f5;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #1d4ed8;
                font-weight: 600;
            }
            QProgressBar {
                height: 16px;
                border: 1px solid #d0d5dd;
                border-radius: 4px;
                background: #ffffff;
                text-align: center;
            }
            QProgressBar::chunk {
                background: #2563eb;
                border-radius: 3px;
            }
            """
        )

    def _status_label(self, text):
        label = QtGui.QLabel(text)
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        label.setWordWrap(True)
        return label

    def _on_start_plan(self):
        user_input = self.input_edit.toPlainText().strip()
        if not user_input:
            self._log("错误: 请输入建模需求。")
            return

        self._reset_run_view()
        self._runner.set_debug_mode(self.debug_checkbox.isChecked())
        if self.debug_checkbox.isChecked():
            self._log(f"[调试] 已开启，日志将写入: {get_debug_sessions_dir()}")

        self._set_status("生成计划中")
        self._set_exec_buttons(False)
        self.start_plan_btn.setEnabled(False)
        self._runner.start_plan(user_input)

    def _on_plan_generated(self, result):
        self.start_plan_btn.setEnabled(True)
        self.step_btn.setEnabled(True)
        self.auto_btn.setEnabled(True)
        self.session_value.setText(result.get("session_id", "-"))
        self._populate_plan(result)
        self._sync_status_from_plan(result)
        self._set_status("计划已生成")
        self._log("\n可以点击 [单步] 逐轮观察，也可以点击 [自动] 连续执行。")

    def _on_step(self):
        self._runner.set_debug_mode(self.debug_checkbox.isChecked())
        self._set_status("执行单步")
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self._runner.run_step()

    def _on_auto(self):
        self._runner.set_debug_mode(self.debug_checkbox.isChecked())
        self._set_status("自动执行")
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.auto_btn.setEnabled(False)
        self.step_btn.setEnabled(False)
        self._runner.run_auto()

    def _on_step_completed(self, result):
        kind = result.get("kind") or "act"
        tool = result.get("tool") or result.get("tool_name") or "-"
        status = result.get("status", "-")
        if kind == "query":
            self._add_trace_row("查询", tool, status, self._summarize_query(result))
            self.tabs.setCurrentWidget(self.trace_table)
        else:
            self._add_trace_row("执行", tool, status, self._summarize_execution(result))

    def _on_evaluation_completed(self, result):
        self._sync_status_from_plan(result)
        validator_results = result.get("validator_results") or []
        for item in validator_results:
            status = "通过" if item.get("passed") else "警告"
            if item.get("validator") in ("verify_object_exists", "verify_shape_valid") and not item.get("passed"):
                status = "失败"
            self._add_trace_row(
                "验证",
                item.get("validator", "-"),
                status,
                self._summarize_validator(item),
            )
        if validator_results:
            self.tabs.setCurrentWidget(self.trace_table)

    def _on_phase_changed(self, phase_id):
        self.phase_value.setText(phase_id)
        for index, step_id in enumerate(self._phase_order):
            item = self._phase_items.get(step_id)
            if not item:
                continue
            if step_id == phase_id:
                item.setText(1, "当前")
                self.plan_tree.setCurrentItem(item)
                self._set_row_color(item, "#1d4ed8")
            elif phase_id in self._phase_order and index < self._phase_order.index(phase_id):
                item.setText(1, "已完成")
                self._set_row_color(item, "#047857")
            else:
                item.setText(1, "待执行")
                self._set_row_color(item, "#475467")

    def _on_execution_finished(self, success, message):
        self._set_exec_buttons(False)
        self.step_btn.setEnabled(True)
        self.auto_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.start_plan_btn.setEnabled(True)
        self._set_status("完成" if success else "已停止")
        if success:
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("100%")
        self._log(f"\n=== 执行结束: {message} ===")

    def _on_error(self, message):
        self._log(f"错误: {message}")
        self._set_status("错误")
        self.start_plan_btn.setEnabled(True)
        self._set_exec_buttons(False)

    def _set_exec_buttons(self, enabled):
        self.step_btn.setEnabled(enabled)
        self.auto_btn.setEnabled(enabled)

    def _on_debug_toggled(self, checked):
        set_debug_mode(checked)
        self._runner.set_debug_mode(checked)
        state = "开启" if checked else "关闭"
        self._log(f"[调试] Debug trace 已{state}")

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

    def _reset_run_view(self):
        self.log_edit.clear()
        self.plan_tree.clear()
        self.trace_table.setRowCount(0)
        self._phase_items = {}
        self._phase_order = []
        self.session_value.setText("-")
        self.phase_value.setText("-")
        self.step_value.setText("-")
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")

    def _populate_plan(self, result):
        self.plan_tree.clear()
        self._phase_items = {}
        self._phase_order = []

        steps = []
        queue = result.get("abstract_step_queue") or {}
        if queue.get("steps"):
            steps = queue.get("steps", [])
        else:
            steps = result.get("phases", [])

        current = (
            (result.get("current_abstract_step") or {}).get("step_id")
            or queue.get("current_step_id")
            or result.get("current_phase_id")
        )

        for index, step in enumerate(steps):
            step_id = step.get("step_id") or step.get("phase_id") or f"step_{index + 1}"
            title = step.get("title") or step.get("intent") or step.get("description") or ""
            success = step.get("success_criteria") or step.get("expected_result") or ""
            status = "当前" if step_id == current or (not current and index == 0) else "待执行"
            item = QtGui.QTreeWidgetItem([step_id, status, self._compact(f"{title} {success}")])
            self.plan_tree.addTopLevelItem(item)
            self._phase_items[step_id] = item
            self._phase_order.append(step_id)
            self._set_row_color(item, "#1d4ed8" if status == "当前" else "#475467")

        self.plan_tree.resizeColumnToContents(0)
        self.plan_tree.resizeColumnToContents(1)

    def _sync_status_from_plan(self, result):
        queue = result.get("abstract_step_queue") or {}
        current_step = result.get("current_abstract_step") or {}
        current_id = current_step.get("step_id") or queue.get("current_step_id") or result.get("updated_current_phase_id")
        if current_id:
            self.phase_value.setText(current_id)
            self.step_value.setText(current_step.get("title") or current_step.get("description") or current_id)
            self._on_phase_changed(current_id)
        self._update_progress(queue)

    def _update_progress(self, queue):
        steps = queue.get("steps", []) if queue else []
        if not steps:
            return
        done = 0
        for step in steps:
            status = str(step.get("status", "")).lower()
            if status in ("completed", "done", "success"):
                done += 1
        value = int(round((done / float(len(steps))) * 100))
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(f"{done}/{len(steps)}")

    def _add_trace_row(self, kind, name, status, summary):
        row = self.trace_table.rowCount()
        self.trace_table.insertRow(row)
        values = [kind, name, status, summary]
        for col, value in enumerate(values):
            item = QtGui.QTableWidgetItem(str(value or "-"))
            if status in ("失败", "error"):
                item.setForeground(QtGui.QBrush(QtGui.QColor("#b42318")))
            elif status in ("警告", "warning"):
                item.setForeground(QtGui.QBrush(QtGui.QColor("#b54708")))
            elif status in ("通过", "success"):
                item.setForeground(QtGui.QBrush(QtGui.QColor("#027a48")))
            self.trace_table.setItem(row, col, item)
        self.trace_table.resizeRowsToContents()

    def _summarize_query(self, result):
        query_result = result.get("query_result") or {}
        tool = result.get("tool") or ""
        if tool == "measure_gap":
            return "axis={axis}, gap={gap}, relation={relation}".format(
                axis=query_result.get("axis", "-"),
                gap=query_result.get("gap", query_result.get("signed_distance", "-")),
                relation=query_result.get("relation", "-"),
            )
        if tool == "compare_orientation":
            return "expected={expected}, actual={actual}, passed={passed}".format(
                expected=query_result.get("expected_axis", "-"),
                actual=query_result.get("actual_axis", "-"),
                passed=query_result.get("passed", "-"),
            )
        if tool == "summarize_document":
            objects = query_result.get("objects") or []
            return f"objects={len(objects)}"
        target = result.get("query_target") or ", ".join(result.get("query_targets") or [])
        bbox = query_result.get("bbox") or {}
        topo = query_result.get("topology") or {}
        if bbox:
            return self._compact(f"target={target} bbox={bbox}")
        if topo:
            return self._compact(
                "target={target} type={type} valid={valid} volume={volume}".format(
                    target=target,
                    type=query_result.get("type", "-"),
                    valid=topo.get("is_valid", "-"),
                    volume=topo.get("volume", "-"),
                )
            )
        return self._compact(f"target={target} type={query_result.get('type', '-')}")

    def _summarize_execution(self, result):
        if result.get("status") != "success":
            return result.get("message", "")
        produced = result.get("produced_objects") or []
        if produced:
            return "produced=" + ", ".join(produced)
        return result.get("message") or "无新对象"

    def _summarize_validator(self, item):
        if item.get("passed"):
            return item.get("message") or "通过"
        parts = [
            item.get("error_code") or item.get("message") or "未通过",
            f"expected={item.get('expected')}" if item.get("expected") is not None else "",
            f"actual={item.get('actual')}" if item.get("actual") is not None else "",
            f"delta={item.get('delta')}" if item.get("delta") is not None else "",
        ]
        if item.get("repair_hint"):
            parts.append(f"hint={item.get('repair_hint')}")
        return self._compact(" ".join(p for p in parts if p))

    def _set_status(self, text):
        self.status_value.setText(text)

    def _set_row_color(self, item, color):
        brush = QtGui.QBrush(QtGui.QColor(color))
        for col in range(self.plan_tree.columnCount()):
            item.setForeground(col, brush)

    def _compact(self, text, limit=180):
        text = " ".join(str(text or "").split())
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _log(self, text):
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
