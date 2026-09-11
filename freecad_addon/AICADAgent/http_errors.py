"""把 HTTP 传输层异常翻译成用户能照着做的提示（不依赖 FreeCAD / Qt）。

面板原先直接把 `str(exc)` 抛给用户，服务没启动时他看到的是一句
`<urlopen error [WinError 10061] 由于目标计算机积极拒绝，无法连接。>`
—— 既不知道错在哪，也不知道下一步做什么。这里统一翻译成「原因 + 怎么修」。
"""

from __future__ import annotations

import json
import socket
import urllib.error

_START_CMD = (
    "cd agent_service && .venv\\Scripts\\activate && "
    "uvicorn app.main:app --host 127.0.0.1 --port 8765"
)


def _winerror(exc: BaseException) -> int | None:
    value = getattr(exc, "winerror", None)
    return int(value) if value is not None else None


def _http_error_body(exc: BaseException) -> str:
    """读 HTTPError 的响应体（服务端 500 会带 detail / request_id）。"""
    reader = getattr(exc, "read", None)
    if not callable(reader):
        return ""
    try:
        raw = reader()
    except Exception:  # noqa: BLE001 - 读不到就算了
        return ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    text = str(raw or "").strip()
    if not text:
        return ""
    # 服务端约定回 JSON；能解析就取 detail，否则原文截断
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if detail:
                rid = payload.get("request_id")
                return f"{detail}" + (f"（request_id={rid}）" if rid else "")
    except Exception:  # noqa: BLE001
        pass
    return text[:300]


def describe_http_failure(exc: BaseException, *, base_url: str) -> str:
    """单行、可照做的失败说明。"""
    # urllib 把底层 OSError 包在 URLError.reason 里，要先揭开才能判断类型
    reason = getattr(exc, "reason", exc)

    if isinstance(reason, ConnectionRefusedError) or _winerror(reason) == 10061:
        return (
            f"Agent 服务未启动（{base_url} 拒绝连接）。"
            f"请先启动服务再重试：{_START_CMD}"
        )

    if isinstance(reason, (socket.gaierror,)):
        return f"Agent 服务地址无法解析：{base_url}（检查 base_url 配置）"

    if isinstance(reason, (TimeoutError, socket.timeout)):
        return (
            f"请求 Agent 服务超时（{base_url}）。"
            "复杂模型生成较慢，可稍后重试；若反复超时请重启服务并查看其控制台日志"
        )

    if isinstance(reason, (ConnectionResetError, ConnectionAbortedError)):
        return f"与 Agent 服务的连接被中断（{base_url}）。服务可能刚重启，请重试"

    if isinstance(exc, urllib.error.HTTPError):
        # 500 只报「Internal Server Error」等于没报；带上服务端给的 detail
        detail = _http_error_body(exc)
        if detail:
            return f"Agent 服务返回 HTTP {exc.code}（{base_url}）：{detail}"
        return f"Agent 服务返回 HTTP {exc.code} {exc.reason}（{base_url}）"

    return f"请求 Agent 服务失败（{base_url}）：{exc}"
