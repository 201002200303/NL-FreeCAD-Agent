"""execute_cad_program 服务端预校验：明显危险的 code 不下发客户端。"""

from app.workflow.chat import prefilter_tool_calls


def test_prefilter_rejects_dangerous_cad_code():
    calls = [
        {
            "tool": "execute_cad_program",
            "args": {"code": "import os\ncad.box(name='X', size=(1,1,1), center=(0,0,0))"},
        }
    ]
    result = prefilter_tool_calls(calls)
    assert result[0].get("blocked") is True
    assert result[0].get("preflight_error")
    # 保留原文，便于模型对照修改
    assert "import os" in (result[0]["args"].get("code") or "")


def test_prefilter_allows_valid_cad_code():
    code = 'x = cad.box(name="X", size=(1,1,1), center=(0,0,0))'
    calls = [{"tool": "execute_cad_program", "args": {"code": code}}]
    result = prefilter_tool_calls(calls)
    assert result[0]["args"]["code"] == code
    assert not result[0].get("preflight_error")
