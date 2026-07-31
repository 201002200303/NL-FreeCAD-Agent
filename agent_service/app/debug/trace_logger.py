"""LLM / API trace logging for debug mode.

Human-readable entry point per LLM call:
  <step_dir>/llm_01_trace.md

Sections: meta → tools seen → system prompt → user context → model output.
Raw JSON kept alongside for machine replay.
"""

from __future__ import annotations

import json
import logging
import os
import re
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_logger = logging.getLogger(__name__)

_trace_session: ContextVar[Optional["TraceSession"]] = ContextVar("trace_session", default=None)
_current_step_name: ContextVar[Optional[str]] = ContextVar("current_step_name", default=None)

_SESSION_README = """# Debug Session

按时间顺序打开子目录，**优先看每个 LLM 调用的 `llm_XX_trace.md`**。

每个 `llm_XX_trace.md` 包含：
1. 元信息（endpoint / model）
2. 模型看到的可用工具列表
3. 完整 system prompt
4. 完整 user message（文档状态 / 记忆 / 当前阶段等上下文）
5. 模型输出（parsed JSON + raw content）

其它文件（可选）：
- `session_summary.json` — 步骤索引
- `meta.json` / `request_payload.json` / `api_response.json` — API 原始请求响应
- `llm_XX_parsed_output.json` / `llm_XX_raw_response.json` — 机器可读
- `executions/` — FreeCAD 工具执行结果
"""


def _default_debug_dir() -> Path:
    env_dir = os.getenv("LLM_DEBUG_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(__file__).resolve().parent.parent.parent / "debug_sessions"


def is_debug_enabled(client_debug: bool = False) -> bool:
    """True when env LLM_DEBUG=1 or client explicitly requests debug."""
    env_on = os.getenv("LLM_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
    return env_on or client_debug


def get_trace_session() -> Optional["TraceSession"]:
    return _trace_session.get()


def set_trace_session(session: Optional["TraceSession"]) -> None:
    _trace_session.set(session)


def get_current_step_name() -> Optional[str]:
    return _current_step_name.get()


def set_current_step_name(step_name: Optional[str]) -> None:
    _current_step_name.set(step_name)


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _extract_tool_names(system_prompt: str) -> list[str]:
    """Extract tool headings like `### create_box` from the system prompt."""
    names = re.findall(r"^###\s+([a-z][a-z0-9_]*)\s*$", system_prompt, flags=re.MULTILINE)
    # Preserve order, drop duplicates
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _build_llm_trace_md(
    *,
    label: str,
    step_name: str,
    model: str,
    system_prompt: str,
    user_message: str,
    parsed: dict | None,
    raw_content: str | None,
    reasoning: str | None,
    error: str | None,
    usage: dict | None,
) -> str:
    tools = _extract_tool_names(system_prompt)
    tool_section = (
        f"共 {len(tools)} 个工具：\n\n"
        + "\n".join(f"- `{t}`" for t in tools)
        if tools
        else "_未能从 system prompt 解析出工具标题（prompt 中可能未按 `### tool_name` 列出）_"
    )

    parts = [
        f"# {label} — LLM Trace",
        "",
        "## 0. 元信息",
        "",
        f"- **step**: `{step_name}`",
        f"- **model**: `{model}`",
        f"- **time**: {datetime.now().isoformat(timespec='seconds')}",
    ]
    if usage:
        parts.append(f"- **usage**: `{json.dumps(usage, ensure_ascii=False)}`")
    if error:
        parts.append(f"- **error**: `{error}`")
    parts.extend([
        "",
        "## 1. 模型看到的可用工具",
        "",
        tool_section,
        "",
        "## 2. System Prompt（完整）",
        "",
        system_prompt.strip() or "_(empty)_",
        "",
        "## 3. User Message / 上下文（完整）",
        "",
        "此处即模型本轮收到的用户侧上下文：文档状态摘要、工作记忆、当前阶段、校验结果等。",
        "",
        user_message.strip() or "_(empty)_",
        "",
        "## 4. 模型输出",
        "",
    ])

    if reasoning:
        parts.extend([
            "### Reasoning",
            "",
            str(reasoning).strip(),
            "",
        ])

    if parsed is not None:
        parts.extend([
            "### Parsed JSON",
            "",
            "```json",
            json.dumps(parsed, ensure_ascii=False, indent=2, default=_json_default),
            "```",
            "",
        ])
    elif raw_content:
        parts.extend([
            "### Raw content（未能解析为 JSON）",
            "",
            "```",
            str(raw_content),
            "```",
            "",
        ])
    elif error:
        parts.extend([
            f"调用失败：{error}",
            "",
        ])
    else:
        parts.extend(["_(no output)_", ""])

    if parsed is not None and raw_content:
        parts.extend([
            "### Raw content",
            "",
            "```",
            str(raw_content),
            "```",
            "",
        ])

    return "\n".join(parts)


class TraceSession:
    """One modeling session debug folder with monotonic step counter."""

    def __init__(self, session_id: str, root_dir: Path):
        self.session_id = session_id
        self.root_dir = root_dir
        self.step_counter = 0
        self.llm_call_counter = 0
        self._summary: dict[str, Any] = {
            "session_id": session_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "how_to_read": "Open each step folder and read llm_XX_trace.md first.",
            "steps": [],
        }
        self.root_dir.mkdir(parents=True, exist_ok=True)
        _write_text(self.root_dir / "README.md", _SESSION_README)
        _write_json(self.root_dir / "session_summary.json", self._summary)

    @classmethod
    def start(cls, session_id: str, root_dir: Path | None = None) -> "TraceSession":
        base = root_dir or _default_debug_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = base / f"{session_id}_{ts}"
        return cls(session_id, folder)

    @classmethod
    def open_existing(cls, session_id: str, root_dir: Path | None = None) -> Optional["TraceSession"]:
        """Attach to latest folder for session_id (next_step / evaluate)."""
        base = root_dir or _default_debug_dir()
        if not base.exists():
            return None
        candidates = sorted(
            [p for p in base.iterdir() if p.is_dir() and p.name.startswith(f"{session_id}_")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return None
        session = cls.__new__(cls)
        session.session_id = session_id
        session.root_dir = candidates[0]
        session.llm_call_counter = 0
        session._summary = {
            "session_id": session_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "how_to_read": "Open each step folder and read llm_XX_trace.md first.",
            "steps": [],
        }
        summary_path = session.root_dir / "session_summary.json"
        if summary_path.exists():
            try:
                session._summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        session.step_counter = len(session._summary.get("steps", []))
        readme = session.root_dir / "README.md"
        if not readme.exists():
            _write_text(readme, _SESSION_README)
        return session

    @property
    def path(self) -> str:
        return str(self.root_dir)

    def next_step_name(self, endpoint: str, phase_id: str | None = None, call_id: str | None = None) -> str:
        self.step_counter += 1
        parts = [f"{self.step_counter:03d}", endpoint]
        if phase_id:
            parts.append(phase_id)
        if call_id:
            parts.append(call_id)
        return "_".join(parts)

    def next_llm_label(self) -> str:
        self.llm_call_counter += 1
        return f"llm_{self.llm_call_counter:02d}"

    def _record_step(self, step_name: str, endpoint: str, meta: dict | None = None) -> None:
        entry = {
            "step_name": step_name,
            "endpoint": endpoint,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "read_first": f"{step_name}/llm_01_trace.md",
        }
        if meta:
            entry.update(meta)
        self._summary.setdefault("steps", []).append(entry)
        _write_json(self.root_dir / "session_summary.json", self._summary)

    def log_api_request(
        self,
        step_name: str,
        endpoint: str,
        payload: dict,
        *,
        phase_id: str | None = None,
    ) -> None:
        step_dir = self.root_dir / step_name
        step_dir.mkdir(parents=True, exist_ok=True)
        self.llm_call_counter = 0

        meta = {
            "endpoint": endpoint,
            "phase_id": phase_id,
            "session_id": self.session_id,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "read_first": "llm_01_trace.md (after LLM call)",
        }
        _write_json(step_dir / "meta.json", meta)
        _write_json(step_dir / "request_payload.json", payload)

        doc_state = payload.get("document_state")
        if doc_state is not None:
            _write_json(step_dir / "document_state.json", doc_state)

        self._record_step(step_name, endpoint, {"phase_id": phase_id})

    def log_api_response(self, step_name: str, response: dict) -> None:
        step_dir = self.root_dir / step_name
        step_dir.mkdir(parents=True, exist_ok=True)
        _write_json(step_dir / "api_response.json", response)

    def log_execution(
        self,
        step_name: str,
        tool_call: dict,
        execution_result: dict,
        *,
        document_state: dict | None = None,
        call_id: str | None = None,
    ) -> None:
        step_dir = self.root_dir / step_name
        step_dir.mkdir(parents=True, exist_ok=True)

        cid = call_id or tool_call.get("call_id") or execution_result.get("call_id")
        if cid:
            exec_dir = step_dir / "executions"
            exec_dir.mkdir(parents=True, exist_ok=True)
            _write_json(exec_dir / f"{cid}_tool_call.json", tool_call)
            _write_json(exec_dir / f"{cid}_result.json", execution_result)
            if document_state is not None:
                _write_json(exec_dir / f"{cid}_document_state.json", document_state)
        else:
            _write_json(step_dir / "tool_call.json", tool_call)
            _write_json(step_dir / "execution_result.json", execution_result)
            if document_state is not None:
                _write_json(step_dir / "document_state_after.json", document_state)

    def log_llm_call(
        self,
        step_name: str,
        *,
        label: str,
        system_prompt: str,
        user_message: str,
        raw_response: Any,
        parsed: dict | None,
        model: str,
        error: str | None = None,
    ) -> None:
        step_dir = self.root_dir / step_name
        step_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{label}_" if label else ""

        raw_payload: dict[str, Any] = {"model": model}
        if error:
            raw_payload["error"] = error

        raw_content: str | None = None
        reasoning: str | None = None
        usage: dict | None = None

        if raw_response is not None:
            if hasattr(raw_response, "model_dump"):
                raw_payload["response"] = raw_response.model_dump(mode="json")
            elif hasattr(raw_response, "to_dict"):
                raw_payload["response"] = raw_response.to_dict()
            else:
                raw_payload["response"] = str(raw_response)

            try:
                msg = raw_response.choices[0].message
                raw_content = msg.content
                raw_payload["content"] = raw_content
                reasoning = getattr(msg, "reasoning_content", None) or getattr(msg, "thinking", None)
                if reasoning:
                    raw_payload["reasoning"] = reasoning
            except Exception:
                pass

            try:
                usage_obj = raw_response.usage
                if usage_obj:
                    usage = (
                        usage_obj.model_dump(mode="json")
                        if hasattr(usage_obj, "model_dump")
                        else dict(usage_obj)
                    )
                    raw_payload["usage"] = usage
            except Exception:
                pass

        # Primary human-readable artifact
        _write_text(
            step_dir / f"{prefix}trace.md",
            _build_llm_trace_md(
                label=label or "llm",
                step_name=step_name,
                model=model,
                system_prompt=system_prompt,
                user_message=user_message,
                parsed=parsed,
                raw_content=raw_content,
                reasoning=str(reasoning) if reasoning else None,
                error=error,
                usage=usage,
            ),
        )

        # Machine-readable companions
        _write_json(step_dir / f"{prefix}raw_response.json", raw_payload)
        if parsed is not None:
            _write_json(step_dir / f"{prefix}parsed_output.json", parsed)
