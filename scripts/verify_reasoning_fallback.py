from types import SimpleNamespace
from app.llm.llm_provider import _extract_json_object, _message_text

reasoning = (
    'json\n{\n  "decision": "execute",\n  "phase_id": "P2",\n'
    '  "tool_calls": [{"call_id": "P2_S5", "tool": "get_object_detail"}],\n'
    '  "message": "need detail"\n}\n```'
)
msg = SimpleNamespace(content="", reasoning_content=reasoning)
obj = _extract_json_object(_message_text(msg))
assert obj["decision"] == "execute"
assert obj["tool_calls"][0]["tool"] == "get_object_detail"
print("OK", obj["phase_id"])
