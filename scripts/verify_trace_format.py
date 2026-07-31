import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
from app.debug.trace_logger import TraceSession, _build_llm_trace_md, _extract_tool_names

sys_p = """## tools
### create_box
desc
### create_cylinder
desc
### get_object_detail
"""
assert _extract_tool_names(sys_p) == ["create_box", "create_cylinder", "get_object_detail"]
md = _build_llm_trace_md(
    label="llm_01",
    step_name="002_next_step_P1",
    model="deepseek-v4-flash",
    system_prompt=sys_p,
    user_message="当前文档有 Base",
    parsed={"decision": "execute"},
    raw_content='{"decision":"execute"}',
    reasoning=None,
    error=None,
    usage=None,
)
assert "## 1. 模型看到的可用工具" in md
assert "`create_box`" in md
assert "## 2. System Prompt" in md
assert "## 3. User Message" in md
assert "## 4. 模型输出" in md

with tempfile.TemporaryDirectory() as d:
    s = TraceSession.start("test", Path(d))
    s.log_api_request("001_start_plan", "start_plan", {"user_input": "box"})
    s.log_llm_call(
        "001_start_plan",
        label="llm_01",
        system_prompt=sys_p,
        user_message="做一个盒子",
        raw_response=None,
        parsed={"goal": "box"},
        model="m",
    )
    step = Path(s.path) / "001_start_plan"
    assert (step / "llm_01_trace.md").exists()
    assert (Path(s.path) / "README.md").exists()
    assert not (step / "llm_01_system_prompt.md").exists()
    print((step / "llm_01_trace.md").read_text(encoding="utf-8")[:500])
print("OK")
