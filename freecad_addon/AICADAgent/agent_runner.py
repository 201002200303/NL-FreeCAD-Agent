# agent_runner.py — V0.7 Closed-loop Agent controller (QThread-based)

import json
import urllib.request
from typing import Optional
from PySide import QtCore, QtGui

import FreeCAD

from AICADAgent.document_state import get_document_state
from AICADAgent.executor import CadToolExecutor
from AICADAgent.debug_settings import is_debug_mode, get_debug_sessions_dir
from AICADAgent.session_memory import SessionMemory
from AICADAgent.viewport import capture_viewport

AGENT_BASE_URL = "http://127.0.0.1:8765"


def _format_soft_plan(plan: dict | None) -> str:
    if not plan:
        return ""
    items = plan.get("items") or plan.get("phases") or []
    if not items:
        return ""
    lines = []
    for it in items:
        if isinstance(it, dict):
            st = it.get("status") or "pending"
            title = it.get("title") or it.get("intent") or ""
            iid = it.get("id") or it.get("phase_id") or ""
            lines.append(f"[{st}] {iid} {title}".strip())
        else:
            lines.append(str(it))
    return "\n".join(lines)


class ChatSession:
    """对话式会话：一个文档 + 一条持续上下文。"""

    def __init__(self, user_goal: str = ""):
        self.session_id: Optional[str] = None
        self.user_goal = user_goal
        self.name_map: dict = {}
        self.soft_plan: Optional[dict] = None
        self.memory = SessionMemory(goal=user_goal, user_input=user_goal)
        self.plan_mode = True
        self.vision_enabled = False


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
        self.abstract_step_queue = high_level_plan.get("abstract_step_queue")
        self.current_abstract_step = high_level_plan.get("current_abstract_step")
        self.memory = SessionMemory(
            goal=high_level_plan.get("goal", ""),
            user_input=user_input,
        )
        self.memory.update_progress(
            current_phase_id=self.current_phase_id,
            current_abstract_step=self.current_abstract_step,
            abstract_step_queue=self.abstract_step_queue,
            high_level_plan=high_level_plan,
        )

    def update_name_map(self, name_map_update: dict):
        """Update name_map with new mappings from tool execution."""
        self.name_map.update(name_map_update)

    def add_to_history(self, entry: dict):
        """Add an execution history entry."""
        self.history.append(entry)

    def get_history_summary(self, max_recent: int = 20) -> dict:
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

    def record_tool_result(self, tool_call: dict, exec_result: dict):
        """Append history and refresh compressed session memory."""
        call_id = tool_call.get("call_id", exec_result.get("call_id", "unknown"))
        tool_name = tool_call.get("tool", exec_result.get("tool", ""))
        name_map_update = exec_result.get("name_map_update", {})
        if name_map_update:
            self.update_name_map(name_map_update)
        entry = {
            "call_id": call_id,
            "tool": tool_name,
            "status": exec_result.get("status"),
            "produced_objects": exec_result.get("produced_objects", []),
            "name_map_update": name_map_update,
            "message": exec_result.get("message"),
            "kind": exec_result.get("kind"),
            "query_target": exec_result.get("query_target"),
            "query_targets": exec_result.get("query_targets"),
            "query_result": exec_result.get("query_result"),
        }
        self.add_to_history(entry)
        self.memory.update_from_tool(
            tool_call,
            exec_result,
            phase_id=self.current_phase_id,
            name_map=self.name_map,
        )

    def refresh_memory_from_document(self, document_state: dict | None = None):
        doc_state = document_state if document_state is not None else get_document_state()
        self.memory.sync_from_document(doc_state)
        self.memory.update_progress(
            current_phase_id=self.current_phase_id,
            current_abstract_step=self.current_abstract_step,
            abstract_step_queue=self.abstract_step_queue,
            high_level_plan=self.high_level_plan,
        )

    def get_session_memory_pack(self) -> dict:
        return self.memory.build_pack()


class HTTPWorker(QtCore.QThread):
    """Worker thread for HTTP requests to Agent service."""

    request_completed = QtCore.Signal(dict)
    request_failed = QtCore.Signal(str)

    def __init__(
        self,
        endpoint: str,
        payload: Optional[dict] = None,
        debug_mode: bool = False,
        method: str = "POST",
        parent=None,
    ):
        super().__init__(parent)
        self.endpoint = endpoint
        self.payload = payload
        self.debug_mode = debug_mode
        self.method = method

    def run(self):
        try:
            url = f"{AGENT_BASE_URL}{self.endpoint}"
            headers = {"Content-Type": "application/json"}
            if self.debug_mode:
                headers["X-Debug-Mode"] = "1"
            data = None
            if self.method == "POST":
                data = json.dumps(self.payload or {}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers=headers,
                method=self.method,
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
    evaluation_completed = QtCore.Signal(dict)
    phase_changed = QtCore.Signal(str)
    execution_finished = QtCore.Signal(bool, str)  # (success, message)
    error_occurred = QtCore.Signal(str)
    session_restored = QtCore.Signal(dict)
    paused_state_changed = QtCore.Signal(bool)
    # 对话式 UI
    chat_reply = QtCore.Signal(dict)  # ChatResponse（session 元信息）
    chat_event = QtCore.Signal(dict)  # {kind: user|assistant|thinking|system, text, meta?}
    soft_plan_updated = QtCore.Signal(dict)
    busy_changed = QtCore.Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.session: Optional[AgentSession] = None
        self.chat: Optional[ChatSession] = None
        self.executor: Optional[CadToolExecutor] = None
        self.http_worker: Optional[HTTPWorker] = None
        self.auto_mode = False
        self.paused = False
        self.stopped = False
        self.debug_mode = is_debug_mode()
        self.debug_session_path: Optional[str] = None
        self.debug_step_name: Optional[str] = None
        self._before_step_state: Optional[dict] = None
        self._last_tool_call: Optional[dict] = None
        self._last_batch_results: list[dict] = []
        self._lifecycle_worker: Optional[HTTPWorker] = None
        self._restore_worker: Optional[HTTPWorker] = None
        self._chat_busy = False
        self._capabilities: dict = {}
        self._pending_user_message: Optional[str] = None
        self._chat_epoch = 0  # 作废进行中的 HTTP 回调，防叠批
        self._tool_queue: list = []
        self._tool_results: list = []
        self._tool_batch_epoch = 0

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
        """Start a closed-loop session: global plan → step-by-step execution."""
        self.log_message.emit(f"→ 生成全局计划: {user_input[:80]}...")

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

        # Create session — server response is authoritative for harness state
        self.session = AgentSession(
            user_input=result.get("user_input", ""),
            high_level_plan=result,
        )
        self.session.session_id = result.get("session_id", self.session.session_id)
        self.session.abstract_step_queue = result.get("abstract_step_queue")
        self.session.current_abstract_step = result.get("current_abstract_step")
        if self.session.current_abstract_step:
            self.session.current_phase_id = self.session.current_abstract_step.get("step_id")
        elif self.session.phases:
            self.session.current_phase_id = self.session.phases[0]["phase_id"]

        try:
            self.session.refresh_memory_from_document(get_document_state())
        except Exception:
            pass

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
        self.session.refresh_memory_from_document(doc_state)
        payload = self._debug_payload({
            "session_id": self.session.session_id,
            "user_input": self.session.user_input,
            "high_level_plan": self.session.high_level_plan,
            "current_phase_id": self.session.current_phase_id,
            "document_state": doc_state,
            "execution_history": history_summary,
            "session_memory": self.session.get_session_memory_pack(),
            "name_map": self.session.name_map,
            "abstract_step_queue": self.session.abstract_step_queue,
            "current_abstract_step": self.session.current_abstract_step,
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

        if result.get("abstract_step_queue") is not None:
            self.session.abstract_step_queue = result["abstract_step_queue"]
        self.session.current_abstract_step = (
            result.get("current_abstract_step") or self.session.current_abstract_step
        )
        # Canonical phase follows abstract step when present.
        step = self.session.current_abstract_step
        phase_id = (step or {}).get("step_id") or result.get("phase_id")
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

        self._before_step_state = get_document_state()
        self._last_batch_results = []

        # Execute each tool call
        for tool_call in tool_calls:
            if self.stopped or self.paused:
                break

            call_id = tool_call.get("call_id", "unknown")
            tool_name = tool_call.get("tool", "")
            self.log_message.emit(f"  [{call_id}] {tool_name}...")

            try:
                # Execute tool call (in main thread)
                self._last_tool_call = tool_call
                exec_result = self.executor.execute_tool_call(tool_call)
                exec_result.setdefault("tool", tool_name)
                exec_result.setdefault("call_id", call_id)

                # Log result
                if exec_result.get("status") == "success":
                    if exec_result.get("kind") == "query":
                        target = exec_result.get("query_target") or ", ".join(exec_result.get("query_targets", []))
                        self.log_message.emit(f"  [query] {call_id}: {tool_name} {target}")
                    else:
                        produced = exec_result.get("produced_objects", [])
                        self.log_message.emit(f"  [ok] {call_id}: 生成 {', '.join(produced) if produced else '无新对象'}")
                else:
                    msg = exec_result.get("message", "未知错误")
                    self.log_message.emit(f"  [error] {call_id}: {msg}")

                self.session.record_tool_result(tool_call, exec_result)
                self._last_batch_results.append(
                    {"tool_call": tool_call, "result": exec_result}
                )
                try:
                    self.session.refresh_memory_from_document(get_document_state())
                except Exception:
                    pass

                self.step_completed.emit(exec_result)
                self._log_tool_execution(tool_call, exec_result)

            except Exception as e:
                self.log_message.emit(f"  [✗] {call_id}: 执行异常 - {e}")
                error_result = {
                    "status": "error",
                    "message": str(e),
                    "tool": tool_name,
                    "call_id": call_id,
                }
                self.session.record_tool_result(tool_call, error_result)
                self._last_batch_results.append(
                    {"tool_call": tool_call, "result": error_result}
                )

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

        # Pick the most informative entry from this batch: the first FAILED
        # call if any (so evaluate sees the real problem), else the last one.
        batch = self._last_batch_results or []
        focus = None
        for item in batch:
            if (item.get("result") or {}).get("status") != "success":
                focus = item
                break
        if focus is None and batch:
            focus = batch[-1]

        if focus:
            focus_call = focus.get("tool_call") or {}
            focus_result = dict(focus.get("result") or {})
        else:
            last_entry = self.session.history[-1] if self.session.history else {}
            focus_call = self._last_tool_call or {
                "call_id": last_entry.get("call_id"),
                "tool": last_entry.get("tool"),
            }
            focus_result = dict(last_entry)

        # Attach a compact whole-batch summary so evaluate is not blind to
        # the other N-1 calls executed in this step.
        if len(batch) > 1:
            focus_result["batch_summary"] = [
                {
                    "call_id": (item.get("tool_call") or {}).get("call_id"),
                    "tool": (item.get("tool_call") or {}).get("tool"),
                    "status": (item.get("result") or {}).get("status"),
                    "produced_objects": (item.get("result") or {}).get(
                        "produced_objects"
                    ),
                    "message": (item.get("result") or {}).get("message"),
                }
                for item in batch
            ]

        # Build evaluate request
        payload = self._debug_payload({
            "session_id": self.session.session_id,
            "last_tool_call": focus_call,
            "execution_result": focus_result,
            "before_state": self._before_step_state,
            "document_state": doc_state_after,
            "execution_history": self.session.get_history_summary(),
            "session_memory": self.session.get_session_memory_pack(),
            "name_map": self.session.name_map,
            "high_level_plan": self.session.high_level_plan,
            "current_phase_id": self.session.current_phase_id,
            "current_abstract_step": self.session.current_abstract_step,
            "abstract_step_queue": self.session.abstract_step_queue,
        })

        # Make HTTP request
        self.http_worker = HTTPWorker("/agent/evaluate_step", payload, self.debug_mode)
        self.http_worker.request_completed.connect(self._on_evaluate_completed)
        self.http_worker.request_failed.connect(self._on_request_failed)
        self.http_worker.start()

    def _on_evaluate_completed(self, result: dict):
        """Handle evaluate_step response."""
        self._update_debug_info(result)
        self.evaluation_completed.emit(result)
        decision = result.get("decision", "")
        phase_status = result.get("phase_status", "")

        if decision == "continue":
            self._sync_session_from_evaluate(result)
            if self.auto_mode and not self.paused and not self.stopped:
                # Use QTimer to schedule next step (avoid deep recursion)
                QtCore.QTimer.singleShot(100, self.execute_next_step)
            else:
                self.log_message.emit("⏸ 等待用户指令继续")

        elif decision == "repair":
            self.log_message.emit(f"↻ 需要修复: {result.get('message', '')}")
            # Execute repair steps, then close the loop with a fresh evaluate
            # (previously the repair result was never evaluated).
            repair_calls = result.get("repair_tool_calls", [])
            if repair_calls:
                self.log_message.emit(f"→ 执行修复步骤 ({len(repair_calls)} 个)...")
                self._before_step_state = get_document_state()
                self._last_batch_results = []
                for tool_call in repair_calls:
                    try:
                        self._last_tool_call = tool_call
                        exec_result = self.executor.execute_tool_call(tool_call)
                        exec_result.setdefault("tool", tool_call.get("tool"))
                        exec_result.setdefault("call_id", tool_call.get("call_id", "repair"))
                        self.session.record_tool_result(tool_call, exec_result)
                        self._last_batch_results.append(
                            {"tool_call": tool_call, "result": exec_result}
                        )
                        try:
                            self.session.refresh_memory_from_document(get_document_state())
                        except Exception:
                            pass
                        self._log_tool_execution(tool_call, exec_result)
                        if exec_result.get("status") == "success":
                            self.log_message.emit(f"  [✓] 修复成功")
                        else:
                            self.log_message.emit(f"  [✗] 修复失败: {exec_result.get('message', '')}")
                    except Exception as e:
                        self.log_message.emit(f"  [✗] 修复异常: {e}")
                        self._last_batch_results.append(
                            {
                                "tool_call": tool_call,
                                "result": {
                                    "status": "error",
                                    "message": str(e),
                                    "tool": tool_call.get("tool"),
                                    "call_id": tool_call.get("call_id", "repair"),
                                },
                            }
                        )
                # Evaluate the repair result before moving on
                if not self.stopped:
                    QtCore.QTimer.singleShot(100, self._request_evaluation)
            elif self.auto_mode and not self.paused and not self.stopped:
                QtCore.QTimer.singleShot(100, self.execute_next_step)

        elif decision == "skip_and_continue":
            self._sync_session_from_evaluate(result)
            self.log_message.emit(f"⚠ 跳过当前步骤: {result.get('message', '')}")
            if self.auto_mode and not self.paused and not self.stopped:
                QtCore.QTimer.singleShot(100, self.execute_next_step)

        elif decision == "finish":
            self.log_message.emit("✓ 建模完成")
            self.execution_finished.emit(True, result.get("message", "建模完成"))

        elif decision == "replan":
            self.log_message.emit(f"↻ 需要重新规划: {result.get('message', '')}")
            self._sync_session_from_evaluate(result)
            if self.auto_mode and not self.paused and not self.stopped:
                QtCore.QTimer.singleShot(100, self.execute_next_step)
            else:
                self.log_message.emit("replan recorded; continue when ready")

        elif decision == "abort":
            self.log_message.emit(f"✗ 终止: {result.get('message', '')}")
            self.execution_finished.emit(False, result.get("message", "终止"))

        else:
            self.log_message.emit(f"⚠ 未知评估决策: {decision}")

    def _current_queue_step(self, queue: Optional[dict]) -> Optional[dict]:
        if not queue:
            return None
        current_id = queue.get("current_step_id")
        steps = queue.get("steps", [])
        if current_id:
            for step in steps:
                if step.get("step_id") == current_id:
                    return step
        return steps[0] if steps else None

    def _sync_session_from_evaluate(self, result: dict):
        """Sync session state from server evaluate response (single source of truth)."""
        if not self.session:
            return
        if result.get("abstract_step_queue") is not None:
            self.session.abstract_step_queue = result["abstract_step_queue"]
        if "current_abstract_step" in result:
            self.session.current_abstract_step = result.get("current_abstract_step")
        # Abstract step is authoritative; updated_current_phase_id must not drift ahead.
        step = self.session.current_abstract_step
        phase_id = (step or {}).get("step_id") or result.get("updated_current_phase_id")
        if phase_id and phase_id != self.session.current_phase_id:
            self.session.current_phase_id = phase_id
            self.log_message.emit(f"→ 进入下一阶段: {phase_id}")
            self.phase_changed.emit(phase_id)
        self.session.memory.update_from_evaluate(result, self.session.high_level_plan)
        try:
            self.session.refresh_memory_from_document(get_document_state())
        except Exception:
            pass

    def _on_request_failed(self, error_msg: str):
        """Handle HTTP request failure."""
        self.error_occurred.emit(f"HTTP 请求失败: {error_msg}")
        if "404" in error_msg:
            self.log_message.emit(
                "✗ Agent 服务不可用或版本过旧。"
                "请从 NL-FreeCAD-Agent\\agent_service 启动: "
                ".venv\\Scripts\\uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload"
            )
        else:
            self.log_message.emit(f"✗ 无法连接到 Agent 服务: {error_msg}")
            self.log_message.emit(
                "请确保 Agent 服务已启动: uvicorn app.main:app --host 127.0.0.1 --port 8765"
            )

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

    def _active_session_id(self) -> Optional[str]:
        if self.chat and self.chat.session_id:
            return self.chat.session_id
        if self.session:
            return self.session.session_id
        return None

    def pause(self):
        """Pause execution and persist USER_PAUSED + document snapshot."""
        self.paused = True
        self.paused_state_changed.emit(True)
        self.log_message.emit("⏸ 已暂停（状态已保存到服务端）")
        sid = self._active_session_id()
        if not sid:
            return
        try:
            doc_state = get_document_state()
        except Exception:
            doc_state = None
        payload = {"document_state": doc_state, "reason": "user_pause"}
        self._lifecycle_worker = HTTPWorker(
            f"/agent/session/{sid}/pause",
            payload,
            self.debug_mode,
        )
        self._lifecycle_worker.start()  # fire-and-forget

    def resume(self):
        """Resume: ask server to diff document, then continue auto if needed."""
        if not self.paused:
            return
        sid = self._active_session_id()
        if not sid:
            self.paused = False
            self.paused_state_changed.emit(False)
            return
        try:
            doc_state = get_document_state()
        except Exception:
            doc_state = None
        self._lifecycle_worker = HTTPWorker(
            f"/agent/session/{sid}/resume",
            {"document_state": doc_state},
            self.debug_mode,
        )
        self._lifecycle_worker.request_completed.connect(self._on_resume_completed)
        self._lifecycle_worker.request_failed.connect(
            lambda e: self._continue_after_resume()
        )
        self._lifecycle_worker.start()

    def _on_resume_completed(self, result: dict):
        changes = result.get("document_changes")
        if changes and changes.get("changed"):
            self.log_message.emit(
                f"⚠ 检测到暂停期间文档被手工修改: {changes.get('summary')}"
            )
            try:
                if self.chat:
                    self.chat.memory.sync_from_document(get_document_state())
                elif self.session:
                    self.session.refresh_memory_from_document(get_document_state())
            except Exception:
                pass
            if self.chat:
                self._emit_chat(
                    "system",
                    "检测到暂停期间文档有手工修改："
                    f"{changes.get('summary') or changes}。"
                    "已记入上下文，可继续说下一步。",
                )
        ckpt = result.get("checkpoint_id")
        if ckpt:
            self.log_message.emit(f"[runtime] checkpoint={ckpt}")
        self._continue_after_resume()

    def _continue_after_resume(self):
        self.paused = False
        self.paused_state_changed.emit(False)
        self.log_message.emit("▶ 已恢复（对话模式请继续发消息，或等自动工具批继续）")
        if self.chat:
            # 暂停期间入队的消息，恢复后发出
            if not self._chat_busy:
                QtCore.QTimer.singleShot(0, self._flush_pending_user_message)
            return
        if self.auto_mode and not self.stopped:
            self.execute_next_step()

    def restore_session(self, session_id: str):
        """GET /agent/session/{id} → rebuild AgentSession + executor idempotency."""
        self.log_message.emit(f"→ 恢复会话: {session_id}...")
        self._restore_worker = HTTPWorker(
            f"/agent/session/{session_id}",
            debug_mode=self.debug_mode,
            method="GET",
        )
        self._restore_worker.request_completed.connect(self._on_restore_completed)
        self._restore_worker.request_failed.connect(self._on_request_failed)
        self._restore_worker.start()

    def _on_restore_completed(self, result: dict):
        if result.get("status") != "ok":
            self.error_occurred.emit(f"恢复失败: {result.get('message')}")
            return
        session_id = result.get("session_id") or ""
        run_state = result.get("run_state") or {}
        plan = dict(run_state.get("high_level_plan") or {})
        plan.setdefault("session_id", session_id)
        if not plan.get("phases") and plan.get("abstract_step_queue"):
            # Prefer queue steps as phase view when plan payload is thin
            pass
        user_input = result.get("user_input") or plan.get("user_input") or ""
        self.session = AgentSession(user_input=user_input, high_level_plan=plan)
        self.session.session_id = session_id
        self.session.abstract_step_queue = run_state.get("abstract_step_queue")
        self.session.current_abstract_step = run_state.get("current_abstract_step")
        self.session.current_phase_id = (
            run_state.get("current_phase_id") or self.session.current_phase_id
        )
        self.session.name_map = dict(run_state.get("name_map") or {})
        self.session.memory.restore_from_pack(run_state.get("session_memory"))
        try:
            self.executor = CadToolExecutor()
        except RuntimeError as e:
            self.error_occurred.emit(f"初始化执行器失败: {e}")
            return
        self.executor.name_map = dict(self.session.name_map)
        self.executor.seed_completed_call_ids(result.get("completed_action_ids"))
        try:
            self.session.refresh_memory_from_document(get_document_state())
        except Exception:
            pass
        self.paused = False
        self.stopped = False
        self.log_message.emit(f"✓ 会话已恢复: {self.session.session_id}")
        # Trigger resume endpoint so server diffs against last pause snapshot
        self.paused = True
        self.session_restored.emit(result)
        self.resume()

    def answer_and_continue(self, answer: str):
        """Append user clarification and continue the closed loop."""
        if not self.session:
            self.error_occurred.emit("No session")
            return
        answer = (answer or "").strip()
        if not answer:
            self.error_occurred.emit("回答为空")
            return
        self.session.user_input = (
            f"{self.session.user_input}\n[用户补充] {answer}"
        )
        self.paused = False
        self.stopped = False
        self.log_message.emit(f"← 用户补充: {answer[:120]}")
        self.execute_next_step()

    def stop(self):
        """Stop execution. In-flight chat 作废；若有排队消息则随后发出。"""
        self.stopped = True
        self.paused = False
        self.paused_state_changed.emit(False)
        self._chat_epoch += 1  # 丢弃进行中的 HTTP 回调 / 工具队列
        self._tool_queue = []
        self._tool_results = []
        self.log_message.emit("⏹ 已停止")
        self.execution_finished.emit(False, "用户停止")
        self._set_chat_busy(False)  # → 刷新排队消息

    # ── 对话式主循环（Cursor / Claude Code 形态）──────────────────

    def fetch_capabilities(self):
        worker = HTTPWorker("/agent/capabilities", method="GET", parent=self)
        worker.request_completed.connect(self._on_capabilities)
        worker.request_failed.connect(lambda e: self.log_message.emit(f"能力探测失败: {e}"))
        worker.start()
        self._lifecycle_worker = worker

    def _on_capabilities(self, result: dict):
        self._capabilities = result or {}
        vision = (result or {}).get("vision") or {}
        self.log_message.emit(
            f"服务端: chat={result.get('chat')} vision_available={vision.get('available')} "
            f"plan_default={result.get('plan_mode_default')}"
        )
        if self.chat is not None and not vision.get("available"):
            # 服务端不可用时不要假装开着
            self.chat.vision_enabled = False

    def set_plan_mode(self, enabled: bool):
        if self.chat is None:
            self.chat = ChatSession()
        self.chat.plan_mode = bool(enabled)

    def set_vision_enabled(self, enabled: bool):
        if self.chat is None:
            self.chat = ChatSession()
        vision = (self._capabilities or {}).get("vision") or {}
        if enabled and self._capabilities and not vision.get("available", True):
            self.log_message.emit("视觉辅助不可用：检查 VISION_ENABLED / VISION_MODEL")
            self.chat.vision_enabled = False
            return
        self.chat.vision_enabled = bool(enabled)

    def _emit_chat(self, kind: str, text: str, **meta):
        text = (text or "").strip()
        if not text:
            return
        self.chat_event.emit({"kind": kind, "text": text, "meta": meta or {}})

    def send_chat(self, message: str):
        """用户发消息。忙时入队，等当前轮结束或用户点停止后再发（不叠 HTTP）。"""
        message = (message or "").strip()
        if not message:
            self.error_occurred.emit("消息为空")
            return
        if self.chat is None:
            self.chat = ChatSession(user_goal=message)
        elif not self.chat.user_goal:
            self.chat.user_goal = message
        if self.executor is None:
            self.executor = CadToolExecutor()

        self._emit_chat("user", message)

        if self._chat_busy:
            self._enqueue_user_message(message)
            self.log_message.emit(f"… 已排队（当前轮结束后发送）: {message[:60]}")
            self._emit_chat(
                "thinking",
                "已排队：当前任务结束后发送（或点停止提前结束）",
                label="queue",
            )
            self.chat_reply.emit(
                {
                    "status": "queued",
                    "session_id": self.chat.session_id or "",
                    "message": "",
                    "tool_calls": [],
                }
            )
            return

        self.stopped = False
        self.paused = False
        self._post_chat(message=message, tool_results=None)

    def _enqueue_user_message(self, message: str):
        if self._pending_user_message:
            self._pending_user_message = f"{self._pending_user_message}\n\n{message}"
        else:
            self._pending_user_message = message

    def _flush_pending_user_message(self):
        """busy 降为 False 后调用：发出排队中的用户消息。"""
        if self._chat_busy or self.paused:
            return
        pending = (self._pending_user_message or "").strip()
        if not pending:
            return
        self._pending_user_message = None
        self.stopped = False
        self.log_message.emit(f"→ 发送排队消息: {pending[:80]}")
        self._post_chat(message=pending, tool_results=None)

    def compress_chat_context(self, keep_recent_turns: int = 4):
        if not self.chat or not self.chat.session_id:
            self.error_occurred.emit("没有可压缩的会话")
            return
        if self._chat_busy:
            self.error_occurred.emit("当前轮未结束，请稍后再压缩上下文")
            return
        payload = {
            "session_id": self.chat.session_id,
            "keep_recent_turns": keep_recent_turns,
            "debug_mode": self.debug_mode,
        }
        self.log_message.emit("→ 压缩上下文…")
        self._chat_epoch += 1
        epoch = self._chat_epoch
        self._set_chat_busy(True)
        worker = HTTPWorker("/agent/compress", payload, self.debug_mode, parent=self)
        worker.request_completed.connect(
            lambda r, e=epoch: self._on_compress_done(r, e)
        )
        worker.request_failed.connect(lambda err, e=epoch: self._on_chat_failed(err, e))
        self.http_worker = worker
        worker.start()

    def _on_compress_done(self, result: dict, epoch: int = 0):
        if epoch and epoch != self._chat_epoch:
            return
        self._set_chat_busy(False)
        msg = result.get("message") or "压缩完成"
        self.log_message.emit(f"✓ {msg}")
        self._emit_chat("system", msg)
        self.chat_reply.emit(
            {
                "status": "awaiting_user",
                "session_id": (self.chat.session_id if self.chat else ""),
                "message": "",
                "tool_calls": [],
                "context_chars": result.get("context_chars", 0),
                "turn_count": result.get("turn_count", 0),
            }
        )

    def _post_chat(self, *, message: str = "", tool_results=None):
        try:
            doc_state = get_document_state()
        except Exception as e:
            self.error_occurred.emit(f"无法读取文档状态: {e}")
            self._set_chat_busy(False)
            return

        viewport = None
        if self.chat and self.chat.vision_enabled:
            viewport = capture_viewport(1024)
            if viewport:
                self.log_message.emit("→ 已截取视口供视觉检查")

        memory = None
        if self.chat:
            try:
                self.chat.memory.sync_from_document(doc_state)
                memory = self.chat.memory.build_pack()
            except Exception:
                memory = None

        payload = {
            "session_id": self.chat.session_id if self.chat else None,
            "message": message or "",
            "document_state": doc_state,
            "tool_results": tool_results or [],
            "viewport_image": viewport,
            "plan_mode": self.chat.plan_mode if self.chat else True,
            "vision_enabled": self.chat.vision_enabled if self.chat else False,
            "session_memory": memory,
            "name_map": dict(self.chat.name_map) if self.chat else {},
            "soft_plan": self.chat.soft_plan if self.chat else None,
            "user_goal": self.chat.user_goal if self.chat else "",
            "debug_mode": self.debug_mode,
        }
        self._chat_epoch += 1
        epoch = self._chat_epoch
        self._set_chat_busy(True)
        preview = (message or "（回传工具结果）")[:80]
        self.log_message.emit(f"→ chat: {preview}")
        worker = HTTPWorker("/agent/chat", payload, self.debug_mode, parent=self)
        worker.request_completed.connect(
            lambda r, e=epoch: self._on_chat_response(r, e)
        )
        worker.request_failed.connect(lambda err, e=epoch: self._on_chat_failed(err, e))
        self.http_worker = worker
        worker.start()

    def _on_chat_failed(self, err: str, epoch: int = 0):
        if epoch and epoch != self._chat_epoch:
            return
        self._set_chat_busy(False)
        self.error_occurred.emit(err)

    def _on_chat_response(self, result: dict, epoch: int = 0):
        if epoch and epoch != self._chat_epoch:
            self.log_message.emit("（忽略过期的 chat 响应）")
            return
        self._update_debug_info(result)
        if not self.chat:
            self.chat = ChatSession()
        sid = result.get("session_id")
        if sid:
            self.chat.session_id = sid

        self._publish_chat_response(result)
        self.chat_reply.emit(result)

        status = result.get("status", "")
        tool_calls = result.get("tool_calls") or []

        if self.stopped or self.paused:
            self._set_chat_busy(False)
            return

        if status == "awaiting_tools" and tool_calls:
            self._execute_chat_tools(tool_calls)
            return

        self._set_chat_busy(False)
        if status == "done":
            self.execution_finished.emit(True, result.get("message") or "完成")
        elif status == "error":
            self.error_occurred.emit(result.get("message") or "chat error")

    def _publish_chat_response(self, result: dict):
        """把一轮 ChatResponse 拆成 transcript 事件：thinking + 正式回复。"""
        if result.get("soft_plan") is not None:
            self.chat.soft_plan = result.get("soft_plan")
            self.soft_plan_updated.emit(self.chat.soft_plan or {})
            plan_text = _format_soft_plan(self.chat.soft_plan)
            if plan_text:
                self._emit_chat("thinking", plan_text, label="plan")

        vision = result.get("vision") or {}
        if vision and not vision.get("skipped"):
            vline = f"{vision.get('verdict')}: {vision.get('summary') or ''}".strip()
            issues = vision.get("issues") or []
            if issues:
                vline += "\n" + "\n".join(f"- {i}" for i in issues[:6])
            self._emit_chat("thinking", vline, label="vision")

        tool_calls = result.get("tool_calls") or []
        if tool_calls:
            lines = []
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                desc = tc.get("description") or ""
                lines.append(f"{tc.get('call_id') or ''} {tc.get('tool')} {desc}".strip())
            self._emit_chat("thinking", "\n".join(lines), label="tools")

        msg = (result.get("message") or "").strip()
        if result.get("question"):
            msg = (msg + "\n\n" + result["question"]).strip() if msg else result["question"]
        if msg:
            self._emit_chat("assistant", msg)
        elif result.get("status") == "error":
            self._emit_chat("system", result.get("message") or "错误")

    def _execute_chat_tools(self, tool_calls: list):
        """逐个执行工具：每做完一个用 QTimer 让出事件循环，避免 GUI 假死。"""
        if self.executor is None:
            self.executor = CadToolExecutor()
        self._tool_queue = [tc if isinstance(tc, dict) else {} for tc in (tool_calls or [])]
        self._tool_results = []
        self._tool_batch_epoch = self._chat_epoch
        self.log_message.emit(f"→ 执行 {len(self._tool_queue)} 个工具（逐个让出 UI）…")
        QtCore.QTimer.singleShot(0, self._run_next_chat_tool)

    def _run_next_chat_tool(self):
        if self._tool_batch_epoch != self._chat_epoch:
            return  # 已被 stop / 新一轮 chat 作废
        if self.stopped or self.paused:
            self._tool_queue = []
            self._tool_results = []
            self._set_chat_busy(False)
            return
        if not self._tool_queue:
            results = list(self._tool_results)
            self._tool_results = []
            self._post_chat(message="", tool_results=results)
            return

        call = self._tool_queue.pop(0)
        tool = call.get("tool") or "?"
        desc = call.get("description") or ""
        self.log_message.emit(f"⚙ {tool} {desc}")
        self._emit_chat("thinking", f"→ {tool} {desc}".strip(), label="tool")
        try:
            exec_result = self.executor.execute_tool_call(call)
        except Exception as e:
            exec_result = {
                "status": "error",
                "message": str(e),
                "call_id": call.get("call_id"),
                "tool": call.get("tool"),
            }
        status = exec_result.get("status", "?")
        produced = exec_result.get("produced_objects") or []
        if status == "success":
            detail = f"✓ {tool}"
            if produced:
                detail += f" → {', '.join(map(str, produced))}"
        else:
            detail = f"✗ {tool}: {exec_result.get('message') or status}"
        self._emit_chat("thinking", detail, label="tool")

        name_map_update = exec_result.get("name_map_update") or {}
        if name_map_update and self.chat:
            self.chat.name_map.update(name_map_update)
            self.executor.name_map = dict(self.chat.name_map)
        if self.chat:
            try:
                self.chat.memory.update_from_tool(
                    call, exec_result, name_map=self.chat.name_map
                )
            except Exception:
                pass
        self._tool_results.append({"tool_call": call, "execution_result": exec_result})
        self._log_tool_execution(call, exec_result)

        # 让出一帧：处理重绘 / 点击停止，再跑下一个
        try:
            QtGui.QApplication.processEvents(QtCore.QEventLoop.AllEvents, 50)
        except Exception:
            pass
        QtCore.QTimer.singleShot(0, self._run_next_chat_tool)

    def _set_chat_busy(self, busy: bool):
        was = self._chat_busy
        self._chat_busy = busy
        self.busy_changed.emit(busy)
        # 当前轮真正空闲后再发排队消息（暂停中不发）
        if was and not busy and not self.paused:
            QtCore.QTimer.singleShot(0, self._flush_pending_user_message)

    def new_chat(self):
        """开新对话（新 session），文档不变。"""
        self.stopped = True
        self._chat_epoch += 1
        self._pending_user_message = None
        self.chat = ChatSession()
        self.executor = CadToolExecutor()
        self._set_chat_busy(False)
        self.log_message.emit("— 新对话 —")
        self._emit_chat("system", "新对话已开始（文档保留，上下文清空）")
