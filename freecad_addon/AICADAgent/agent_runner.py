# agent_runner.py — V0.7 Closed-loop Agent controller (QThread-based)

import json
import urllib.request
from typing import Optional
from PySide import QtCore

import FreeCAD

from AICADAgent.document_state import get_document_state
from AICADAgent.executor import CadToolExecutor
from AICADAgent.debug_settings import is_debug_mode, get_debug_sessions_dir

AGENT_BASE_URL = "http://127.0.0.1:8765"


class AgentSession:
    """Manages session state for a closed-loop modeling session."""

    def __init__(self, user_input: str, high_level_plan: dict):
        self.user_input = user_input
        self.high_level_plan = high_level_plan
        self.phases = high_level_plan.get("phases", [])
        self.current_phase_id = self.phases[0]["phase_id"] if self.phases else None
        self.history = []
        self.name_map = {}
        self.session_id = high_level_plan.get("session_id", "local_session")

    def update_name_map(self, name_map_update: dict):
        """Update name_map with new mappings from tool execution."""
        self.name_map.update(name_map_update)

    def add_to_history(self, entry: dict):
        """Add an execution history entry."""
        self.history.append(entry)

    def get_history_summary(self, max_recent: int = 5) -> dict:
        """Get a summary of execution history for sending to Agent.

        Returns recent detailed results + older status counts.
        """
        if not self.history:
            return {"recent": [], "summary": {}}

        recent = self.history[-max_recent:]
        older = self.history[:-max_recent] if len(self.history) > max_recent else []

        # Count statuses for older entries
        status_counts = {}
        for entry in older:
            status = entry.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        return {
            "recent": recent,
            "summary": status_counts if status_counts else {},
        }


class HTTPWorker(QtCore.QThread):
    """Worker thread for HTTP requests to Agent service."""

    request_completed = QtCore.Signal(dict)
    request_failed = QtCore.Signal(str)

    def __init__(self, endpoint: str, payload: dict, debug_mode: bool = False, parent=None):
        super().__init__(parent)
        self.endpoint = endpoint
        self.payload = payload
        self.debug_mode = debug_mode

    def run(self):
        try:
            url = f"{AGENT_BASE_URL}{self.endpoint}"
            data = json.dumps(self.payload).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if self.debug_mode:
                headers["X-Debug-Mode"] = "1"
            req = urllib.request.Request(
                url,
                data=data,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                self.request_completed.emit(result)
        except Exception as e:
            self.request_failed.emit(str(e))


class AgentRunner(QtCore.QObject):
    """Closed-loop Agent controller for V0.7.

    Manages the observe-plan-act-evaluate cycle:
    - Runs HTTP requests in QThread to avoid blocking UI
    - Emits signals to main thread for FreeCAD operations
    - Supports auto/step-by-step execution modes
    - Provides pause/stop control
    """

    # Signals for UI updates
    log_message = QtCore.Signal(str)
    plan_generated = QtCore.Signal(dict)
    step_completed = QtCore.Signal(dict)
    phase_changed = QtCore.Signal(str)
    execution_finished = QtCore.Signal(bool, str)  # (success, message)
    error_occurred = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.session: Optional[AgentSession] = None
        self.executor: Optional[CadToolExecutor] = None
        self.http_worker: Optional[HTTPWorker] = None
        self.auto_mode = False
        self.paused = False
        self.stopped = False
        self.debug_mode = is_debug_mode()
        self.debug_session_path: Optional[str] = None
        self.debug_step_name: Optional[str] = None

    def set_debug_mode(self, enabled: bool):
        self.debug_mode = enabled

    def _debug_payload(self, payload: dict) -> dict:
        payload["debug_mode"] = self.debug_mode
        return payload

    def _update_debug_info(self, result: dict):
        path = result.get("debug_session_path")
        step = result.get("debug_step_name")
        if path:
            self.debug_session_path = path
        if step:
            self.debug_step_name = step
        if self.debug_mode and path:
            self.log_message.emit(f"[调试] 日志目录: {path}")

    def _log_tool_execution(self, tool_call: dict, exec_result: dict):
        """Send tool execution trace to Agent (non-blocking best-effort)."""
        if not self.debug_mode or not self.session or not self.debug_step_name:
            return
        try:
            doc_state = get_document_state()
        except Exception:
            doc_state = None
        payload = {
            "session_id": self.session.session_id,
            "step_name": self.debug_step_name,
            "tool_call": tool_call,
            "execution_result": exec_result,
            "document_state": doc_state,
            "debug_mode": True,
        }
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{AGENT_BASE_URL}/agent/log_execution",
                data=data,
                headers={"Content-Type": "application/json", "X-Debug-Mode": "1"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception:
            pass

    def start_plan(self, user_input: str):
        """Start a new modeling session by requesting high-level plan."""
        self.log_message.emit(f"→ 请求生成高层计划: {user_input[:80]}...")

        # Get document state
        try:
            doc_state = get_document_state()
        except Exception as e:
            self.error_occurred.emit(f"无法读取文档状态: {e}")
            return

        # Build request
        payload = self._debug_payload({
            "user_input": user_input,
            "document_state": doc_state,
        })

        # Make HTTP request in worker thread
        self.http_worker = HTTPWorker("/agent/start_plan", payload, self.debug_mode)
        self.http_worker.request_completed.connect(self._on_start_plan_completed)
        self.http_worker.request_failed.connect(self._on_request_failed)
        self.http_worker.start()

    def _on_start_plan_completed(self, result: dict):
        """Handle start_plan response."""
        if result.get("status") != "ok":
            self.error_occurred.emit(f"生成高层计划失败: {result.get('message', '未知错误')}")
            return

        # Create session
        self.session = AgentSession(
            user_input=result.get("user_input", ""),
            high_level_plan=result,
        )

        # Initialize executor
        try:
            self.executor = CadToolExecutor()
        except RuntimeError as e:
            self.error_occurred.emit(f"初始化执行器失败: {e}")
            return

        self.log_message.emit(f"← 高层计划生成成功")
        self.log_message.emit(f"← 目标: {result.get('goal', '')}")

        # Log phases
        for phase in result.get("phases", []):
            self.log_message.emit(f"  [Phase] {phase['phase_id']}: {phase.get('intent', '')}")

        self.plan_generated.emit(result)
        self._update_debug_info(result)

    def execute_next_step(self):
        """Request and execute the next step."""
        if not self.session or not self.executor:
            self.error_occurred.emit("Session not initialized")
            return

        if self.stopped:
            return

        if self.paused:
            self.log_message.emit("⏸ 已暂停")
            return

        # Get current document state
        try:
            doc_state = get_document_state()
        except Exception as e:
            self.error_occurred.emit(f"无法读取文档状态: {e}")
            return

        # Build next_step request
        history_summary = self.session.get_history_summary()
        payload = self._debug_payload({
            "session_id": self.session.session_id,
            "user_input": self.session.user_input,
            "high_level_plan": self.session.high_level_plan,
            "current_phase_id": self.session.current_phase_id,
            "document_state": doc_state,
            "execution_history": history_summary,
            "name_map": self.session.name_map,
        })

        # Make HTTP request
        self.http_worker = HTTPWorker("/agent/next_step", payload, self.debug_mode)
        self.http_worker.request_completed.connect(self._on_next_step_completed)
        self.http_worker.request_failed.connect(self._on_request_failed)
        self.http_worker.start()

    def _on_next_step_completed(self, result: dict):
        """Handle next_step response."""
        self._update_debug_info(result)
        decision = result.get("decision", "")

        # Sync phase from server (may auto-advance P1→P2)
        phase_id = result.get("phase_id")
        if phase_id and phase_id != self.session.current_phase_id:
            self.session.current_phase_id = phase_id
            self.log_message.emit(f"→ 进入阶段: {phase_id}")
            self.phase_changed.emit(phase_id)

        if decision == "finish":
            self.log_message.emit("✓ 建模完成")
            self.execution_finished.emit(True, result.get("message", "建模完成"))
            return

        if decision == "abort":
            self.log_message.emit(f"✗ 无法继续: {result.get('message', '')}")
            self.execution_finished.emit(False, result.get("message", "无法继续"))
            return

        if decision == "ask_user":
            self.log_message.emit(f"? 需要用户输入: {result.get('question', '')}")
            self.execution_finished.emit(False, "需要用户输入")
            return

        if decision not in ["execute", "repair"]:
            self.log_message.emit(f"⚠ 未知决策类型: {decision}")
            return

        # Execute tool calls
        tool_calls = result.get("tool_calls", [])
        if not tool_calls:
            self.log_message.emit("⚠ Agent 返回了空的 tool_calls")
            return

        self.log_message.emit(f"→ 执行 {len(tool_calls)} 个工具调用...")

        # Execute each tool call
        for tool_call in tool_calls:
            if self.stopped or self.paused:
                break

            call_id = tool_call.get("call_id", "unknown")
            tool_name = tool_call.get("tool", "")
            self.log_message.emit(f"  [{call_id}] {tool_name}...")

            try:
                # Execute tool call (in main thread)
                exec_result = self.executor.execute_tool_call(tool_call)

                # Update name_map
                name_map_update = exec_result.get("name_map_update", {})
                self.session.update_name_map(name_map_update)

                # Log result
                if exec_result.get("status") == "success":
                    produced = exec_result.get("produced_objects", [])
                    self.log_message.emit(f"  [✓] {call_id}: 生成 {', '.join(produced) if produced else '无新对象'}")
                else:
                    msg = exec_result.get("message", "未知错误")
                    self.log_message.emit(f"  [✗] {call_id}: {msg}")

                # Add to history
                self.session.add_to_history({
                    "call_id": call_id,
                    "tool": tool_name,
                    "status": exec_result.get("status"),
                    "produced_objects": exec_result.get("produced_objects", []),
                    "name_map_update": name_map_update,
                    "message": exec_result.get("message"),
                })

                self.step_completed.emit(exec_result)
                self._log_tool_execution(tool_call, exec_result)

            except Exception as e:
                self.log_message.emit(f"  [✗] {call_id}: 执行异常 - {e}")
                self.session.add_to_history({
                    "call_id": call_id,
                    "tool": tool_name,
                    "status": "error",
                    "message": str(e),
                })

        # Request evaluation
        self._request_evaluation()

    def _request_evaluation(self):
        """Request Agent to evaluate the last execution step."""
        if not self.session or not self.executor:
            return

        # Get document state (after execution)
        try:
            doc_state_after = get_document_state()
        except Exception as e:
            self.error_occurred.emit(f"无法读取文档状态: {e}")
            return

        # Get last history entry
        last_entry = self.session.history[-1] if self.session.history else {}

        # Build evaluate request
        payload = self._debug_payload({
            "session_id": self.session.session_id,
            "last_tool_call": {
                "call_id": last_entry.get("call_id"),
                "tool": last_entry.get("tool"),
            },
            "execution_result": last_entry,
            "document_state": doc_state_after,
            "execution_history": self.session.get_history_summary(),
            "high_level_plan": self.session.high_level_plan,
            "current_phase_id": self.session.current_phase_id,
        })

        # Make HTTP request
        self.http_worker = HTTPWorker("/agent/evaluate_step", payload, self.debug_mode)
        self.http_worker.request_completed.connect(self._on_evaluate_completed)
        self.http_worker.request_failed.connect(self._on_request_failed)
        self.http_worker.start()

    def _on_evaluate_completed(self, result: dict):
        """Handle evaluate_step response."""
        self._update_debug_info(result)
        decision = result.get("decision", "")
        phase_status = result.get("phase_status", "")

        if decision == "continue":
            # Check if phase changed
            new_phase_id = result.get("updated_current_phase_id")
            if new_phase_id and new_phase_id != self.session.current_phase_id:
                self.session.current_phase_id = new_phase_id
                self.log_message.emit(f"→ 进入下一阶段: {new_phase_id}")
                self.phase_changed.emit(new_phase_id)

            # Continue to next step
            if self.auto_mode and not self.paused and not self.stopped:
                # Use QTimer to schedule next step (avoid deep recursion)
                QtCore.QTimer.singleShot(100, self.execute_next_step)
            else:
                self.log_message.emit("⏸ 等待用户指令继续")

        elif decision == "repair":
            self.log_message.emit(f"↻ 需要修复: {result.get('message', '')}")
            # Execute repair steps
            repair_calls = result.get("repair_tool_calls", [])
            if repair_calls:
                self.log_message.emit(f"→ 执行修复步骤 ({len(repair_calls)} 个)...")
                # Execute repair calls (similar to normal execution)
                for tool_call in repair_calls:
                    try:
                        exec_result = self.executor.execute_tool_call(tool_call)
                        self.session.update_name_map(exec_result.get("name_map_update", {}))
                        self._log_tool_execution(tool_call, exec_result)
                        if exec_result.get("status") == "success":
                            self.log_message.emit(f"  [✓] 修复成功")
                        else:
                            self.log_message.emit(f"  [✗] 修复失败: {exec_result.get('message', '')}")
                    except Exception as e:
                        self.log_message.emit(f"  [✗] 修复异常: {e}")

            # Continue after repair
            if self.auto_mode and not self.paused and not self.stopped:
                QtCore.QTimer.singleShot(100, self.execute_next_step)

        elif decision == "skip_and_continue":
            self.log_message.emit(f"⚠ 跳过当前步骤: {result.get('message', '')}")
            if self.auto_mode and not self.paused and not self.stopped:
                QtCore.QTimer.singleShot(100, self.execute_next_step)

        elif decision == "finish":
            self.log_message.emit("✓ 建模完成")
            self.execution_finished.emit(True, result.get("message", "建模完成"))

        elif decision == "replan":
            self.log_message.emit(f"↻ 需要重新规划: {result.get('message', '')}")
            # For V0.7, just stop and let user restart
            self.execution_finished.emit(False, "需要重新规划")

        elif decision == "abort":
            self.log_message.emit(f"✗ 终止: {result.get('message', '')}")
            self.execution_finished.emit(False, result.get("message", "终止"))

        else:
            self.log_message.emit(f"⚠ 未知评估决策: {decision}")

    def _on_request_failed(self, error_msg: str):
        """Handle HTTP request failure."""
        self.error_occurred.emit(f"HTTP 请求失败: {error_msg}")
        self.log_message.emit(f"✗ 无法连接到 Agent 服务: {error_msg}")
        self.log_message.emit("请确保 Agent 服务已启动: uvicorn app.main:app --host 127.0.0.1 --port 8765")

    def run_auto(self):
        """Start auto execution mode."""
        if not self.session:
            self.error_occurred.emit("No session")
            return

        self.auto_mode = True
        self.paused = False
        self.stopped = False
        self.log_message.emit("→ 开始自动执行...")
        self.execute_next_step()

    def run_step(self):
        """Execute single step (step-by-step mode)."""
        if not self.session:
            self.error_occurred.emit("No session")
            return

        self.auto_mode = False
        self.paused = False
        self.stopped = False
        self.execute_next_step()

    def pause(self):
        """Pause execution."""
        self.paused = True
        self.log_message.emit("⏸ 已暂停")

    def resume(self):
        """Resume execution."""
        if self.paused:
            self.paused = False
            self.log_message.emit("▶ 继续执行...")
            if self.auto_mode:
                self.execute_next_step()

    def stop(self):
        """Stop execution."""
        self.stopped = True
        self.log_message.emit("⏹ 已停止")
        self.execution_finished.emit(False, "用户停止")
