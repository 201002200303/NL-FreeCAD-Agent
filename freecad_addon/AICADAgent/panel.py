# panel.py — AI CAD Agent control panel (PySide)

import json
import urllib.request

from PySide import QtCore, QtGui

import FreeCAD
import FreeCADGui

AGENT_URL = "http://127.0.0.1:8765/agent/plan"


class AICADPanel(QtGui.QDockWidget):
    """Dockable panel for natural language CAD modeling."""

    def __init__(self, parent=None): # 初始化参数，创建实例时自动执行，确定需要传入的父对象，即AICADPanel(mw)，中的mw
        """
        调用父类构造函数，初始化父类部分
        mw = FreeCADGui.getMainWindow()
        ---------------------------------
        input: parent (QMainWindow)
        
        output: None
        """
        super().__init__("AI CAD Agent", parent) # ← "请 QDockWidget 的 __init__ 帮忙设置标题和父窗口"
        
        self.setObjectName("AICADPanel")
        self.setMinimumWidth(350)

        # Main widget
        main_widget = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(main_widget)

        # Input section
        layout.addWidget(QtGui.QLabel("建模需求 (Modeling Request):"))
        self.input_edit = QtGui.QTextEdit()
        self.input_edit.setPlaceholderText(
            "用自然语言描述建模需求...\n"
            "例如: 创建一个 100×60×20mm 的底座"
        )
        self.input_edit.setMaximumHeight(120)
        layout.addWidget(self.input_edit)

        # Generate button
        self.generate_btn = QtGui.QPushButton("生成建模计划 (Generate Plan)")
        self.generate_btn.clicked.connect(self._on_generate_plan)
        layout.addWidget(self.generate_btn)

        # Execute button
        self.execute_btn = QtGui.QPushButton("执行计划 (Execute Plan)")
        self.execute_btn.clicked.connect(self._on_execute_plan)
        self.execute_btn.setEnabled(False)
        layout.addWidget(self.execute_btn)

        # Cache the last plan
        self._last_plan = None

        # Output section
        layout.addWidget(QtGui.QLabel("建模计划 (Plan):"))
        self.log_edit = QtGui.QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText("生成的建模计划将显示在这里...")
        layout.addWidget(self.log_edit)

        self.setWidget(main_widget)

    def _on_generate_plan(self):
        """Handle the 'Generate Plan' button click."""
        user_input = self.input_edit.toPlainText().strip()
        if not user_input:
            self._log("错误: 请输入建模需求。")
            return

        self._log(f"→ 发送请求: {user_input[:80]}...")

        # Gather document state
        try:
            from AICADAgent.document_state import get_document_state
            doc_state = get_document_state()
        except Exception as e:
            self._log(f"警告: 无法读取文档状态 ({e})，使用空状态。")
            doc_state = {
                "document_name": "Unknown",
                "objects": [],
                "selected_objects": [],
            }

        # Build request
        payload = json.dumps({
            "user_input": user_input,
            "document_state": doc_state,
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                AGENT_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            self._log(f"← 状态: {result.get('status')}")
            if result.get("goal"):
                self._log(f"← 目标: {result['goal']}")
            if result.get("assumptions"):
                for a in result["assumptions"]:
                    self._log(f"  假设: {a}")
            if result.get("missing_params"):
                self._log(f"  缺失参数: {result['missing_params']}")
            if result.get("question"):
                self._log(f"  提问: {result['question']}")

            self._log("\n--- Plan JSON ---")
            self._log(json.dumps(result, ensure_ascii=False, indent=2))

            if result.get("plan"):
                self._last_plan = result["plan"]
                self.execute_btn.setEnabled(True)
                self._log(f"\n← 共 {len(result['plan'])} 个步骤:")
                for step in result["plan"]:
                    self._log(
                        f"  {step['step_id']}: {step['description']} "
                        f"[tool={step['tool']}]"
                    )
                self._log("\n点击 [执行计划] 按钮开始建模...")

        except urllib.error.URLError as e:
            self._log(f"错误: 无法连接到 Agent 服务 ({e})")
            self._log("请确保 Agent 服务已启动: uvicorn app.main:app --host 127.0.0.1 --port 8765")
        except json.JSONDecodeError as e:
            self._log(f"错误: 无法解析服务返回的 JSON ({e})")
        except Exception as e:
            self._log(f"错误: {e}")

    def _on_execute_plan(self):
        """Execute the cached plan on the active FreeCAD document."""
        if not self._last_plan:
            self._log("错误: 没有可执行的计划，请先生成建模计划。")
            return

        self._log("\n=== 开始执行建模计划 ===")
        self.execute_btn.setEnabled(False)

        try:
            from AICADAgent.executor import CadToolExecutor
            executor = CadToolExecutor()
        except RuntimeError as e:
            self._log(f"错误: {e}")
            self.execute_btn.setEnabled(True)
            return

        results = executor.execute_plan(self._last_plan)

        success_count = 0
        for r in results:
            step_id = r.get("step_id", "?")
            status = r.get("status", "unknown")
            if status == "success":
                success_count += 1
                self._log(f"  [✓] {step_id}: {r.get('tool', '')} → {r.get('object', r.get('filepath', ''))}")
            else:
                self._log(f"  [✗] {step_id}: {r.get('tool', '')} → {r.get('message', '未知错误')}")

        self._log(f"\n=== 执行完成: {success_count}/{len(results)} 步成功 ===")
        self.execute_btn.setEnabled(True)

    def _log(self, text: str):
        """Append text to the log output."""
        self.log_edit.append(text)
        # Auto-scroll to bottom
        scrollbar = self.log_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


_panel_instance = None  # 定义全局变量


def show_panel():
    """Create or show the AI CAD Agent panel in FreeCAD."""
    global _panel_instance  # 引用全局变量
    mw = FreeCADGui.getMainWindow() # 获取主窗口，便于后续拿过来用，后面mw就是主窗口

    if _panel_instance is None: # 判断是否点开过标签，如果否则创建实例：
        _panel_instance = AICADPanel(mw) # 创建面板实例
        mw.addDockWidget(
            QtCore.Qt.RightDockWidgetArea, _panel_instance
        ) # QMainWindow 的方法，用于添加可停靠面板，指定停靠位置：右侧，要添加的 QDockWidget 实例（即 AICADPanel）
    else:
        _panel_instance.show() # 显示面板
        _panel_instance.raise_() # 提升窗口到最前面
