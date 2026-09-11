"""传输层报错的可读性守卫（D7 同类：错误必须能照着修）。

服务没启动时，面板原样显示 `<urlopen error [WinError 10061] ...>`，
用户无从下手。这里锁住「原因 + 怎么修」的翻译。
"""
import io
import json
import socket
import sys
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "freecad_addon"))

from AICADAgent.http_errors import describe_http_failure  # noqa: E402

BASE = "http://127.0.0.1:8765"


def test_connection_refused_says_service_not_started_and_how_to_start():
    # urllib 会把 OSError 包进 URLError.reason，真实形态就是这个
    exc = urllib.error.URLError(ConnectionRefusedError(10061, "目标计算机积极拒绝，无法连接。"))
    message = describe_http_failure(exc, base_url=BASE)
    assert "未启动" in message
    assert BASE in message
    assert "uvicorn app.main:app" in message
    # 不能让用户继续看到原始 WinError
    assert "urlopen error" not in message


def test_bare_connection_refused_is_handled():
    message = describe_http_failure(ConnectionRefusedError(10061, "refused"), base_url=BASE)
    assert "未启动" in message
    assert "uvicorn app.main:app" in message


def test_timeout_mentions_retry_not_misconfigured_service():
    message = describe_http_failure(socket.timeout("timed out"), base_url=BASE)
    assert "超时" in message
    assert "重试" in message
    assert "uvicorn app.main:app" not in message


def test_http_error_reports_status_code():
    exc = urllib.error.HTTPError(BASE + "/agent/chat", 500, "Internal Server Error", {}, None)
    message = describe_http_failure(exc, base_url=BASE)
    assert "500" in message


def test_http_500_surfaces_server_detail_and_request_id():
    """500 只回「Internal Server Error」等于没回；必须带出服务端给的 detail。"""
    body = json.dumps(
        {
            "detail": "KeyError: 'bbox'",
            "error_type": "KeyError",
            "request_id": "abc123def456",
            "path": "/agent/chat",
        }
    ).encode("utf-8")
    exc = urllib.error.HTTPError(
        BASE + "/agent/chat", 500, "Internal Server Error", {}, io.BytesIO(body)
    )
    message = describe_http_failure(exc, base_url=BASE)
    assert "500" in message
    assert "KeyError" in message
    assert "abc123def456" in message


def test_http_error_with_unreadable_body_still_reports_status():
    """响应体读不到时不能崩，仍要给出状态码。"""
    exc = urllib.error.HTTPError(BASE + "/agent/chat", 503, "Service Unavailable", {}, None)
    message = describe_http_failure(exc, base_url=BASE)
    assert "503" in message


def test_http_error_with_plain_text_body_is_truncated():
    body = io.BytesIO(b"x" * 2000)
    exc = urllib.error.HTTPError(BASE + "/agent/chat", 500, "Internal Server Error", {}, body)
    message = describe_http_failure(exc, base_url=BASE)
    assert "500" in message
    assert len(message) < 800


def test_unknown_error_still_names_the_service():
    message = describe_http_failure(ValueError("boom"), base_url=BASE)
    assert BASE in message
    assert "boom" in message


def test_runner_uses_the_translator_not_raw_str():
    source = (
        REPO_ROOT / "freecad_addon" / "AICADAgent" / "agent_runner.py"
    ).read_text(encoding="utf-8")
    assert "describe_http_failure(e, base_url=AGENT_BASE_URL)" in source
    assert "self.request_failed.emit(str(e))" not in source
