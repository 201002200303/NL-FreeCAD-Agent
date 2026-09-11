"""客户端回传状态必须容错：畸形 `session_memory` / `tool_results` 不得把会话打成 500。

背景：用户在面板看到「Agent 服务返回 HTTP 500 Internal Server Error」，
日志里是 `AttributeError: 'str' object has no attribute 'items'`。
`session_memory` / `tool_results` 在 schema 里只有外层类型约束
（`Optional[dict]` / `list[dict]`），内部值无校验，却直接进宿主提示词组装。
一旦某轮状态变脏，客户端每轮原样重发 → 会话永久 500，用户无法自救。

落点：在 workflow 入口（`chat_turn` / `classify_chat_step`）一次性补齐形状，
下游函数保持「输入已规范」的简单契约。
"""
from fastapi.testclient import TestClient

from app.memory.prompt import build_compact_document_context
from app.schemas.cad_state import CADObject, DocumentState
from app.workflow.sanitize import sanitize_memory_pack, sanitize_tool_results

DOC = DocumentState(
    document_name="T",
    objects=[CADObject(name="A", label="A", type="Part::Box", visible=True)],
    selected_objects=[],
)


# --- sanitize_tool_results ----------------------------------------------------


def test_tool_results_drops_non_dict_items():
    cleaned = sanitize_tool_results(["garbage", 3, {"tool_call": {}, "execution_result": {}}])
    assert cleaned == [{"tool_call": {}, "execution_result": {}}]


def test_tool_results_coerces_scalar_call_and_result():
    cleaned = sanitize_tool_results(
        [{"tool_call": "nope", "execution_result": 5, "extra": "kept-out"}]
    )
    assert cleaned == [{"tool_call": {}, "execution_result": {}}]


def test_tool_results_falsy_returns_none():
    assert sanitize_tool_results(None) is None
    assert sanitize_tool_results([]) is None


def test_tool_results_keeps_wellformed_receipt():
    receipt = {
        "tool_call": {"call_id": "c1", "tool": "execute_cad_program"},
        "execution_result": {"status": "success", "produced_objects": ["A"]},
    }
    assert sanitize_tool_results([receipt]) == [receipt]


# --- sanitize_memory_pack -----------------------------------------------------


def test_memory_pack_drops_non_dict_object_memory():
    pack = sanitize_memory_pack({"object_memory": "boom", "recent_events": 5})
    assert "object_memory" not in pack
    assert pack["recent_events"] == 5  # 其它字段原样保留


def test_memory_pack_drops_non_dict_entries():
    pack = sanitize_memory_pack({"object_memory": {"A": "bad", "B": {"type": "Part::Box"}}})
    assert pack["object_memory"] == {"B": {"type": "Part::Box"}}


def test_memory_pack_drops_non_str_current_target():
    pack = sanitize_memory_pack({"current_target": {"a": 1}, "query_cache": {}})
    assert "current_target" not in pack


def test_memory_pack_drops_non_dict_query_cache():
    pack = sanitize_memory_pack({"query_cache": "boom"})
    assert "query_cache" not in pack


def test_memory_pack_none_and_non_dict():
    assert sanitize_memory_pack(None) is None
    assert sanitize_memory_pack("boom") is None


# --- 清洗后下游照常工作 -------------------------------------------------------


def test_builder_falls_back_to_document_state_after_memory_cleaned():
    pack = sanitize_memory_pack({"object_memory": "boom"})
    text = build_compact_document_context(DOC, pack)
    assert "A" in text


# --- HTTP 边界：端到端不得 500 ------------------------------------------------


def test_chat_endpoint_survives_malformed_client_state():
    from app.main import app

    payload = {
        "message": "继续",
        "document_state": {"document_name": "T", "objects": [], "selected_objects": []},
        "tool_results": [
            {"tool_call": "not-a-dict", "execution_result": 5},
            {"tool_call": {"tool": "execute_cad_program"}, "execution_result": "boom"},
        ],
        "session_memory": {"object_memory": "boom", "recent_events": 5},
        "name_map": {},
        "plan_mode": True,
        "vision_enabled": False,
        "user_goal": "t",
    }
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post("/agent/chat", json=payload)
    assert resp.status_code == 200, resp.text


def test_classify_chat_step_survives_malformed_tool_results():
    from app.workflow.chat import classify_chat_step

    assert classify_chat_step(tool_results=[{"execution_result": 5}]) == "tool_feedback"
