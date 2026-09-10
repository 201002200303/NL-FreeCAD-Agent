"""LLM 输出解析的健壮性：容忍推理模型的常见「脏输出」。

实测背景（deepseek-flash）：模型偶尔在合法 JSON 之后再多吐一个 `}`，
旧的 `_extract_json_object` 兜底取「第一个 { 到最后一个 }」，正好把多余的
`}` 包进切片，于是永远解析失败 → 两次重试全失败 → 用户看到
「LLM 调用失败，请重试或检查 API 配置」。
"""
import json

from app.llm.llm_provider import _extract_json_object


def test_plain_json():
    assert _extract_json_object('{"a": 1}') == {"a": 1}


def test_markdown_fenced_json():
    assert _extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_prefix_without_fence():
    assert _extract_json_object('json\n{"a": 1}') == {"a": 1}


def test_tolerates_trailing_extra_brace():
    """实测坏样本：合法 JSON 后多一个 }。这是用户那次报错的直接原因。"""
    raw = '{"message": "ok", "tool_calls": []}}'
    parsed = _extract_json_object(raw)
    assert parsed["message"] == "ok"


def test_tolerates_several_trailing_braces():
    parsed = _extract_json_object('{"a": 1}}}')
    assert parsed == {"a": 1}


def test_tolerates_trailing_prose():
    raw = '{"a": 1}\n\n以上就是本轮的方案，请确认。'
    assert _extract_json_object(raw) == {"a": 1}


def test_tolerates_two_concatenated_objects():
    """模型有时把同一对象写两遍；取第一个即可。"""
    raw = '{"a": 1}{"a": 2}'
    assert _extract_json_object(raw) == {"a": 1}


def test_tolerates_leading_prose_before_object():
    raw = '好的，这是结果：\n{"a": 1}'
    assert _extract_json_object(raw) == {"a": 1}


def test_real_world_sample_with_nested_code_string():
    """贴近真实坏样本：长 code 字符串 + 多余的收尾括号。"""
    payload = {
        "message": "重建机体",
        "tool_calls": [
            {
                "call_id": "chat_5",
                "tool": "execute_cad_program",
                "args": {
                    "transaction": "restore_mecha_parts",
                    "code": 'cad.delete(["Mecha"])\nfuse("TorsoC", "Head", name="Torso")\n',
                },
            }
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False) + "}"
    parsed = _extract_json_object(raw)
    assert parsed["tool_calls"][0]["args"]["transaction"] == "restore_mecha_parts"
    assert "fuse(" in parsed["tool_calls"][0]["args"]["code"]


def test_raises_when_no_json_at_all():
    import pytest

    with pytest.raises(json.JSONDecodeError):
        _extract_json_object("完全没有 JSON 的一段话")
