"""LLM 调用层的两个实测缺陷守卫：

1. GBK 控制台打印模型输出会崩 —— 崩溃发生在诊断分支里，会把
   「JSON 解析失败」伪装成「API 调用失败」，并丢掉真正的原始输出。
2. 输出撞上 max_tokens 被截断时，错误信息必须点明是截断，
   否则会被误判成模型「写坏了 JSON」而白调参数。
"""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.console import harden_console
from app.llm import llm_provider

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── ① 控制台编码 ────────────────────────────────────────────────


def test_harden_console_switches_streams_to_replace():
    """加固后编码失败应降级成替换字符，而不是抛异常。"""
    raw = io.TextIOWrapper(io.BytesIO(), encoding="gbk")
    old_stdout = sys.stdout
    try:
        sys.stdout = raw
        harden_console()
        assert raw.errors == "replace"
        print("沿 Z 轴 ↔ 镜像")  # 修复前：UnicodeEncodeError
    finally:
        sys.stdout = old_stdout


def test_importing_app_hardens_console_in_a_fresh_process():
    """服务端任何代码只要 import app.* 就应自动加固。"""
    code = (
        "import sys;"
        "sys.path.insert(0, r'%s');"
        "import app;"
        "print(sys.stdout.errors)"
    ) % str(REPO_ROOT / "agent_service")
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "replace"


def test_printing_unencodable_model_output_does_not_raise():
    """实测触发字符：U+2194。在 GBK 流上不得抛异常。"""
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="gbk", errors="replace")
    stream.write("左右对称(沿 Z 轴 ↔ 镜像)")
    stream.flush()


# ── ② 截断 vs 写坏 ──────────────────────────────────────────────


class _FakeMessage:
    def __init__(self, content):
        self.content = content
        self.reasoning_content = ""


class _FakeChoice:
    def __init__(self, content, finish_reason):
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeUsage:
    def __init__(self, completion_tokens=None, reasoning_tokens=None):
        self.completion_tokens = completion_tokens
        if reasoning_tokens is None:
            self.completion_tokens_details = None
        else:
            self.completion_tokens_details = _FakeReasoning(reasoning_tokens)


class _FakeReasoning:
    def __init__(self, reasoning_tokens):
        self.reasoning_tokens = reasoning_tokens


class _FakeResponse:
    def __init__(self, content, finish_reason, usage=None):
        self.choices = [_FakeChoice(content, finish_reason)]
        self.usage = usage


def _patch_openai(monkeypatch, response):
    class _Completions:
        def create(self, **kwargs):
            return response

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr("openai.OpenAI", _Client)


def test_truncated_output_error_names_max_tokens(monkeypatch):
    """finish_reason=length → 必须提示调大 LLM_MAX_TOKENS。"""
    truncated = '{"message": "重建机体", "tool_calls": [{"tool": "execute_cad'
    _patch_openai(monkeypatch, _FakeResponse(truncated, "length"))

    parsed, _resp, error, raw = llm_provider._attempt_llm_call(
        [{"role": "user", "content": "x json"}],
        api_key="k", base_url="http://x", model="m",
    )
    assert parsed is None
    assert error is not None
    assert "截断" in error
    assert "LLM_MAX_TOKENS" in error
    assert raw == truncated


def test_truncated_error_reports_reasoning_tokens(monkeypatch):
    """实测 16384 被推理烧光才截断；错误里必须能看出 token 花在哪。"""
    truncated = '{"message": "重建机体", "tool_calls": [{"tool": "execute_cad'
    _patch_openai(
        monkeypatch,
        _FakeResponse(truncated, "length", usage=_FakeUsage(16384, 16380)),
    )

    _parsed, _resp, error, _raw = llm_provider._attempt_llm_call(
        [{"role": "user", "content": "x json"}],
        api_key="k", base_url="http://x", model="m",
    )
    assert "reasoning_tokens=16380" in error


# ── ③ 输出预算必须容得下推理模型的思考 ──────────────────────────


def test_output_budget_is_high_enough_for_a_reasoning_model():
    """实测：deepseek-flash 的 reasoning token 计入 max_tokens，
    16384 会被思考烧光导致 JSON 截断（面板报「LLM 调用失败」）。
    这里挡住把预算调回小值 —— 旧注释曾断言 16384「够用」，是被实测推翻的。
    """
    # 端点实测上限 393216；下限按实测 16k 饱和值的 4 倍留余量
    assert 65536 <= llm_provider.LLM_MAX_TOKENS <= 393216


def test_timeout_scales_with_the_budget():
    """实测 16k token ≈ 83s。预算调大而超时不调，只是把「截断」换成「超时」。"""
    assert llm_provider.LLM_TIMEOUT_SEC >= 300


def test_config_and_provider_agree_on_output_budget():
    from app import config

    assert config.LLM_MAX_TOKENS == llm_provider.LLM_MAX_TOKENS
    assert config.LLM_TIMEOUT_SEC == llm_provider.LLM_TIMEOUT_SEC


def test_malformed_output_error_is_not_blamed_on_truncation(monkeypatch):
    """finish_reason=stop 时不得误报成截断。"""
    _patch_openai(monkeypatch, _FakeResponse("完全不是 JSON", "stop"))

    parsed, _resp, error, _raw = llm_provider._attempt_llm_call(
        [{"role": "user", "content": "x json"}],
        api_key="k", base_url="http://x", model="m",
    )
    assert parsed is None
    assert "截断" not in (error or "")


def test_trailing_garbage_still_parses(monkeypatch):
    """实测坏样本：合法 JSON + 多余 '}'，必须解析成功而不是走重试。"""
    _patch_openai(
        monkeypatch,
        _FakeResponse('{"message": "ok", "tool_calls": []}}', "stop"),
    )
    parsed, _resp, error, _raw = llm_provider._attempt_llm_call(
        [{"role": "user", "content": "x json"}],
        api_key="k", base_url="http://x", model="m",
    )
    assert error is None
    assert parsed == {"message": "ok", "tool_calls": []}
