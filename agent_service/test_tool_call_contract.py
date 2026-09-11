"""LLM → 客户端的 tool_call 契约：模型越界字段不得打崩响应。

背景：实测 deepseek-flash 会把 `expected_effect` 写成自然语言字符串
（"车身上出现前后两...两侧向顶部内收"），而契约里它是 dict。
后果是 ChatResponse 的 pydantic 校验在 LLM 成功之后才炸 → HTTP 500；
即使侥幸通过，客户端 `session_memory` 的 `expected.get("type")` 也会崩。
"""
import pytest

from app.schemas.session import ToolCall
from app.workflow.sanitize import sanitize_tool_calls


def _call(**kw):
    base = {"tool": "execute_cad_program", "args": {"code": "x = cad.box()\n"}}
    base.update(kw)
    return base


def test_string_expected_effect_is_dropped():
    """实测坏样本：模型把 expected_effect 写成一句话。"""
    out = sanitize_tool_calls(
        [_call(expected_effect="车身上出现前后两处轮拱，两侧向顶部内收")]
    )
    assert out[0]["expected_effect"] is None


def test_dict_expected_effect_is_preserved():
    effect = {"new_object": "Body", "type": "Part::Box"}
    out = sanitize_tool_calls([_call(expected_effect=effect)])
    assert out[0]["expected_effect"] == effect


def test_missing_expected_effect_stays_none():
    out = sanitize_tool_calls([_call()])
    assert out[0]["expected_effect"] is None


@pytest.mark.parametrize("bad", ["文字", 5, ["a"], None])
def test_non_dict_expected_effect_never_reaches_schema(bad):
    """无论模型给什么，都必须能构造成 ToolCall（否则响应在最后一步 500）。"""
    out = sanitize_tool_calls([_call(expected_effect=bad)])
    ToolCall(**out[0])


def test_sanitized_calls_satisfy_chat_response_schema():
    from app.schemas.response import ChatResponse

    out = sanitize_tool_calls([_call(expected_effect="一句话")])
    resp = ChatResponse(status="awaiting_tools", tool_calls=out)
    assert resp.tool_calls[0].expected_effect is None


def test_call_without_tool_is_dropped():
    assert sanitize_tool_calls([{"args": {}}]) == []
    assert sanitize_tool_calls(["garbage"]) == []


def test_call_id_is_generated_when_missing():
    out = sanitize_tool_calls([_call()], prefix="chat")
    assert out[0]["call_id"] == "chat_1"


def test_normalize_chat_result_drops_string_expected_effect():
    """接线检查：真实路径 `_normalize_chat_result` 必须经过清洗。

    这条就是用户遇到的 HTTP 500 —— 崩在 LLM 成功**之后**的响应构造上。
    """
    from app.schemas.response import ChatResponse
    from app.workflow.chat import _normalize_chat_result

    parsed = _normalize_chat_result(
        {
            "message": "按跑车思路建模",
            "tool_calls": [_call(expected_effect="车身上出现前后两处轮拱")],
        },
        soft_plan=None,
        plan_mode=True,
    )
    resp = ChatResponse(status="awaiting_tools", tool_calls=parsed["tool_calls"])
    assert resp.tool_calls[0].expected_effect is None
