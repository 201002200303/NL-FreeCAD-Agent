# agent_runner.py — Chat-first Agent controller (FreeCAD client)

"""对话式建模客户端循环。

主路径：send_chat → POST /agent/chat → 执行 tool_calls → 回传 tool_results → 循环。
旧三段式（start_plan / next_step / evaluate）已移除；服务端实现见 archive。
"""

from __future__ import annotations

import json
import urllib.request
from typing import Optional

from PySide import QtCore, QtGui

from AICADAgent.document_state import get_document_state
from AICADAgent.executor import CadToolExecutor
from AICADAgent.debug_settings import is_debug_mode
from AICADAgent.http_errors import describe_http_failure
from AICADAgent.session_memory import SessionMemory
from AICADAgent.viewport import (
    DEFAULT_VIEWS,
    capture_views,
    extract_tool_capture_images,
    should_autofill_multiview,
)

AGENT_BASE_URL = "http://127.0.0.1:8765"
# 含工具列表的 chat 单轮常 30–90s；视觉+多轮回灌更容易超时，给足余量
HTTP_TIMEOUT_SEC = 600

# 能力探测失败时的退避重试（服务端可能还没启动）
_CAPABILITIES_MAX_RETRIES = 5
_CAPABILITIES_RETRY_MS = 3000


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
        self.phase_state: Optional[dict] = None
        self.vision_memory: Optional[dict] = None
        self.memory = SessionMemory(goal=user_goal, user_input=user_goal)
        self.plan_mode = True
        self.vision_enabled = False


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
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                self.request_completed.emit(result)
        except Exception as e:
            # 服务没起来时 str(e) 只有一句 WinError，用户无法自诊；翻译成能照做的提示
            self.request_failed.emit(describe_http_failure(e, base_url=AGENT_BASE_URL))


class AgentRunner(QtCore.QObject):
    """Chat agent controller: HTTP in QThread, CAD tools on GUI thread."""

    log_message = QtCore.Signal(str)
    execution_finished = QtCore.Signal(bool, str)  # (success, message)
    error_occurred = QtCore.Signal(str)
    paused_state_changed = QtCore.Signal(bool)
    chat_reply = QtCore.Signal(dict)  # ChatResponse meta for UI chrome
    chat_event = QtCore.Signal(dict)  # {kind, text, meta?}
    soft_plan_updated = QtCore.Signal(dict)
    busy_changed = QtCore.Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.chat: Optional[ChatSession] = None
        self.executor: Optional[CadToolExecutor] = None
        self.http_worker: Optional[HTTPWorker] = None
        self.paused = False
        self.stopped = False
        self.debug_mode = is_debug_mode()
        self.debug_session_path: Optional[str] = None
        self.debug_step_name: Optional[str] = None
        self._lifecycle_worker: Optional[HTTPWorker] = None
        self._chat_busy = False
        self._capabilities: dict = {}
        # None=未知（放行）/ True=匹配 / False=已确认不兼容（才阻断）
        self._cad_api_compatible: Optional[bool] = None
        self._capabilities_retry_attempt = 0
        self._pending_user_message: Optional[str] = None
        self._chat_epoch = 0
        self._tool_queue: list = []
        self._tool_results: list = []
        self._tool_batch_epoch = 0

    # ── debug / helpers ───────────────────────────────────────────

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
        """Best-effort debug upload of a single tool result."""
        if not self.debug_mode or not self.debug_step_name:
            return
        sid = self.chat.session_id if self.chat else None
        if not sid:
            return
        try:
            doc_state = get_document_state()
        except Exception:
            doc_state = None
        payload = {
            "session_id": sid,
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

    def _active_session_id(self) -> Optional[str]:
        if self.chat and self.chat.session_id:
            return self.chat.session_id
        return None

    # ── pause / resume / stop ─────────────────────────────────────

    def pause(self):
        """Pause chat loop and persist snapshot on server."""
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
        self._lifecycle_worker.start()

    def resume(self):
        """Resume after pause; flush queued user message if idle."""
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
            lambda _e: self._continue_after_resume()
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
        self.log_message.emit("▶ 已恢复（继续发消息，或等自动工具批继续）")
        if not self._chat_busy:
            QtCore.QTimer.singleShot(0, self._flush_pending_user_message)

    def stop(self):
        """Stop current chat turn; invalidate in-flight HTTP / tool batch."""
        self.stopped = True
        self.paused = False
        self.paused_state_changed.emit(False)
        self._chat_epoch += 1
        self._tool_queue = []
        self._tool_results = []
        self.log_message.emit("⏹ 已停止")
        self.execution_finished.emit(False, "用户停止")
        self._set_chat_busy(False)

    # ── capabilities / mode ───────────────────────────────────────

    def fetch_capabilities(self):
        worker = HTTPWorker("/agent/capabilities", method="GET", parent=self)
        worker.request_completed.connect(self._on_capabilities)
        worker.request_failed.connect(self._on_capabilities_failed)
        worker.start()
        self._lifecycle_worker = worker

    def _on_capabilities(self, result: dict):
        self._capabilities = result or {}
        try:
            from AICADAgent.cad_program.manifest import CAD_API_VERSION
            from AICADAgent.capabilities import evaluate_cad_api_compatibility

            blocked, reason = evaluate_cad_api_compatibility(
                (result or {}).get("cad_api_version"), CAD_API_VERSION
            )
            self._cad_api_compatible = not blocked
            if blocked:
                self.log_message.emit(f"{reason}；已暂停建模执行")
        except Exception as exc:
            # 取不到本地契约不是不兼容证据：保持未知（fail-open）
            self._cad_api_compatible = None
            self.log_message.emit(f"契约版本比较失败: {exc}；本次不阻断建模")
        self._capabilities_retry_attempt = 0
        vision = (result or {}).get("vision") or {}
        self.log_message.emit(
            f"服务端: chat={result.get('chat')} vision_available={vision.get('available')} "
            f"plan_default={result.get('plan_mode_default')}"
        )
        if self.chat is not None and not vision.get("available"):
            self.chat.vision_enabled = False

    def _on_capabilities_failed(self, error: str):
        # 探测失败=None（未知），不阻断；退避重试（服务端可能还没起来）
        self._cad_api_compatible = None
        self.log_message.emit(f"能力探测失败: {error}；本次不阻断建模，稍后重试")
        self._schedule_capabilities_retry()

    def _schedule_capabilities_retry(self):
        if self._capabilities_retry_attempt >= _CAPABILITIES_MAX_RETRIES:
            return
        delay = _CAPABILITIES_RETRY_MS * (self._capabilities_retry_attempt + 1)
        self._capabilities_retry_attempt += 1
        QtCore.QTimer.singleShot(delay, self.fetch_capabilities)

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

    # ── chat loop ─────────────────────────────────────────────────

    def send_chat(self, message: str):
        """用户发消息。忙时入队，等当前轮结束或用户点停止后再发。"""
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
        viewport_images = []
        if self.chat and self.chat.vision_enabled:
            # 仅在有几何且（模型截图 或 CAD 成功补拍）时带图；空文档不截、不评估
            try:
                has_geometry = False
                for obj in (doc_state or {}).get("objects") or []:
                    if isinstance(obj, dict) and obj.get("visible", True):
                        has_geometry = True
                        break
                    if not isinstance(obj, dict):
                        has_geometry = True
                        break
                if has_geometry:
                    viewport_images = extract_tool_capture_images(tool_results)
                    if viewport_images:
                        self.log_message.emit(
                            f"→ 使用模型指定视图: {', '.join(v.get('name','') for v in viewport_images)}"
                        )
                    elif should_autofill_multiview(tool_results):
                        viewport_images = capture_views(list(DEFAULT_VIEWS), max_edge=1024)
                        if viewport_images:
                            self.log_message.emit(
                                f"→ 模型未截图，已自动补拍: {', '.join(v.get('name','') for v in viewport_images)}"
                            )
                elif tool_results:
                    self.log_message.emit("↷ 文档无可见几何，跳过视觉截图")
            except Exception as exc:
                self.log_message.emit(f"↷ 视口截图失败，跳过视觉: {exc}")

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
            "viewport_images": viewport_images,
            "plan_mode": self.chat.plan_mode if self.chat else True,
            "vision_enabled": self.chat.vision_enabled if self.chat else False,
            "session_memory": memory,
            "name_map": dict(self.chat.name_map) if self.chat else {},
            "soft_plan": self.chat.soft_plan if self.chat else None,
            "phase_state": self.chat.phase_state if self.chat else None,
            "vision_memory": self.chat.vision_memory if self.chat else None,
            "user_goal": self.chat.user_goal if self.chat else "",
            "debug_mode": self.debug_mode,
        }
        self._chat_epoch += 1
        epoch = self._chat_epoch
        self._set_chat_busy(True)
        preview = (message or "（回传工具结果）")[:80]
        self.log_message.emit(f"→ chat: {preview}")
        wait_hint = (
            "正在请求模型…"
            if message
            else "正在根据工具结果继续规划…"
        )
        self._emit_chat("thinking", wait_hint, label="wait")
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
        if result.get("phase_state") is not None:
            self.chat.phase_state = result.get("phase_state")
        if result.get("soft_plan") is not None:
            self.chat.soft_plan = result.get("soft_plan")
            self.soft_plan_updated.emit(self.chat.soft_plan or {})
            plan_text = _format_soft_plan(self.chat.soft_plan)
            if plan_text:
                self._emit_chat("thinking", plan_text, label="plan")

        if result.get("vision_memory") is not None:
            self.chat.vision_memory = result.get("vision_memory")

        vision = result.get("vision") or {}
        if vision and not vision.get("skipped"):
            vline = f"{vision.get('verdict')}: {vision.get('summary') or ''}".strip()
            issues = vision.get("issues") or []
            if issues:
                vline += "\n" + "\n".join(f"- {i}" for i in issues[:6])
            if vision.get("revise_blocked"):
                vline += f"\n(本阶段视觉修订已暂停: {vision.get('revise_blocked')})"
            self._emit_chat("thinking", vline, label="vision")
        elif vision.get("skipped") and vision.get("reason") == "empty_document":
            self._emit_chat("thinking", "文档无几何，跳过视觉评估", label="vision")

        tool_calls = result.get("tool_calls") or []
        if tool_calls:
            lines = []
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                desc = tc.get("description") or ""
                lines.append(
                    f"{tc.get('call_id') or ''} {tc.get('tool')} {desc}".strip()
                )
            self._emit_chat("thinking", "\n".join(lines), label="tools")

        msg = (result.get("message") or "").strip()
        if result.get("question"):
            msg = (
                (msg + "\n\n" + result["question"]).strip()
                if msg
                else result["question"]
            )
        if msg:
            self._emit_chat("assistant", msg)
        elif result.get("status") == "error":
            self._emit_chat("system", result.get("message") or "错误")

    def _execute_chat_tools(self, tool_calls: list):
        # fail-open：只有已确认版本不兼容才阻断；未知（探测未回/失败）照常执行
        if self._cad_api_compatible is False:
            self.error_occurred.emit("CAD 程序契约版本不兼容，请同步更新服务端与 FreeCAD 插件")
            self._set_chat_busy(False)
            return
        if self.executor is None:
            self.executor = CadToolExecutor()
        self._tool_queue = [
            tc if isinstance(tc, dict) else {} for tc in (tool_calls or [])
        ]
        self._tool_results = []
        self._tool_batch_epoch = self._chat_epoch
        self.log_message.emit(f"→ 执行 {len(self._tool_queue)} 个工具（逐个让出 UI）…")
        QtCore.QTimer.singleShot(0, self._run_next_chat_tool)

    def _run_next_chat_tool(self):
        if self._tool_batch_epoch != self._chat_epoch:
            return
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

        if call.get("blocked"):
            exec_result = {
                "status": "error",
                "message": call.get("preflight_error") or "服务端预校验拒绝执行",
                "call_id": call.get("call_id"),
                "tool": tool,
                "error_type": "preflight_blocked",
            }
            self._emit_chat("thinking", f"✗ {tool}: {exec_result['message']}", label="tool")
            self._tool_results.append({"tool_call": call, "execution_result": exec_result})
            QtCore.QTimer.singleShot(0, self._run_next_chat_tool)
            return

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
        if exec_result.get("skipped_duplicate"):
            detail = f"↷ 跳过重复 {tool}"
            if produced:
                detail += f"（缓存产出 {', '.join(map(str, produced))}）"
            detail += " — 同 call_id 已执行过，本次未改文档"
        elif status == "success":
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

        try:
            QtGui.QApplication.processEvents(QtCore.QEventLoop.AllEvents, 50)
        except Exception:
            pass
        QtCore.QTimer.singleShot(0, self._run_next_chat_tool)

    def _set_chat_busy(self, busy: bool):
        was = self._chat_busy
        self._chat_busy = busy
        self.busy_changed.emit(busy)
        if was and not busy and not self.paused:
            QtCore.QTimer.singleShot(0, self._flush_pending_user_message)

    def new_chat(self):
        """开新对话（新 session），文档不变。"""
        self.stopped = True
        self._chat_epoch += 1
        self._pending_user_message = None
        self.chat = ChatSession()
        try:
            self.executor = CadToolExecutor()
        except RuntimeError:
            self.executor = None
        self._set_chat_busy(False)
        self.log_message.emit("— 新对话 —")
        self._emit_chat("system", "新对话已开始（文档保留，上下文清空）")
