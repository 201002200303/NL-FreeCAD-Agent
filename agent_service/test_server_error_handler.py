"""全局异常处理：500 必须带回可自诊的信息，而不是裸的 Internal Server Error。

背景：用户在 FreeCAD 面板看到「Agent 服务返回 HTTP 500 Internal Server Error」，
既没有异常类型也没有 request_id，日志里也没有 traceback —— 无从下手。
"""
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client_with_boom():
    """挂一个必定抛异常的路由，验证 handler 的返回体与日志。"""
    from app.main import app

    @app.get("/__test_boom")
    async def _boom():  # pragma: no cover - 仅测试用
        raise KeyError("bbox")

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    app.router.routes = [
        r for r in app.router.routes if getattr(r, "path", "") != "/__test_boom"
    ]


def test_unhandled_exception_returns_actionable_json(client_with_boom):
    resp = client_with_boom.get("/__test_boom")
    assert resp.status_code == 500
    payload = resp.json()
    assert payload["error_type"] == "KeyError"
    assert "bbox" in payload["detail"]
    assert payload["request_id"]
    assert payload["path"] == "/__test_boom"


def test_unhandled_exception_logs_traceback(client_with_boom, caplog):
    with caplog.at_level(logging.ERROR):
        client_with_boom.get("/__test_boom")
    text = caplog.text
    assert "未处理异常" in text
    assert "KeyError" in text
    # 必须真的有 traceback，否则等于没记
    assert "Traceback" in text


def test_health_still_ok(client_with_boom):
    assert client_with_boom.get("/health").status_code == 200
