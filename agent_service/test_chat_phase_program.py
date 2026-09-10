from contextlib import nullcontext

from app.conversation.transcript import Transcript
from app.schemas.cad_state import DocumentState
from app.workflow import chat as chat_mod


def _plan(status="in_progress"):
    return {
        "items": [
            {
                "id": "P1",
                "title": "主体",
                "status": status,
                "acceptance": [
                    {"type": "object_exists", "target": "Main"},
                    {"type": "valid_shape", "target": "Main"},
                ],
            },
            {"id": "P2", "title": "孔槽", "status": "pending"},
        ]
    }


def _doc(valid=True):
    return {
        "document_name": "Doc",
        "objects": [
            {
                "name": "Main",
                "label": "Main",
                "type": "Part::Feature",
                "visible": True,
                "bbox": {
                    "xmin": -0.5, "xmax": 0.5,
                    "ymin": -0.5, "ymax": 0.5,
                    "zmin": -0.5, "zmax": 0.5,
                    "size": [1, 1, 1], "center": [0, 0, 0],
                },
                "topology": {"is_valid": valid, "solids": 1},
                "properties": {},
            }
        ],
    }


def _isolate_chat(monkeypatch, llm_result):
    transcript = Transcript()
    monkeypatch.setattr(chat_mod, "conversation_scope", lambda sid: nullcontext(transcript))
    monkeypatch.setattr(chat_mod, "vision_available", lambda **kw: False)
    monkeypatch.setattr(chat_mod, "call_llm", lambda *args, **kwargs: llm_result)


def test_chat_turn_wraps_agent_code_as_phase_program(monkeypatch):
    _isolate_chat(
        monkeypatch,
        {
            "message": "建立主体",
            "status": "awaiting_tools",
            "soft_plan": _plan(),
            "tool_calls": [
                {
                    "call_id": "T1",
                    "tool": "execute_cad_program",
                    "args": {"code": "cad.box(name='Main', size=(1,1,1), center=(0,0,0))"},
                }
            ],
        },
    )

    result = chat_mod.chat_turn(
        session_id="S1", message="建主体", plan_mode=True, vision_enabled=False
    )

    args = result["tool_calls"][0]["args"]
    assert args["phase_id"] == "P1"
    assert args["execution_key"].startswith("S1:P1:")
    assert result["phase_state"]["status"] == "awaiting_execution"


def test_chat_turn_ignores_agent_attempt_to_bypass_failed_gate(monkeypatch):
    proposed = _plan(status="done")
    proposed["items"][1]["status"] = "in_progress"
    captured = {}

    def fake_llm(user, system, **kwargs):
        captured["user"] = user
        return {
            "message": "继续下一阶段",
            "status": "awaiting_user",
            "soft_plan": proposed,
            "tool_calls": [],
        }

    _isolate_chat(monkeypatch, {})
    monkeypatch.setattr(chat_mod, "call_llm", fake_llm)
    call = {
        "call_id": "T1",
        "tool": "execute_cad_program",
        "args": {
            "phase_id": "P1",
            "program_hash": "h",
            "execution_key": "S1:P1:h",
            "acceptance": _plan()["items"][0]["acceptance"],
            "code": "pass",
        },
    }

    result = chat_mod.chat_turn(
        session_id="S1",
        message="",
        document_state=DocumentState(**_doc(valid=False)),
        tool_results=[
            {
                "tool_call": call,
                "execution_result": {
                    "status": "success",
                    "tool": "execute_cad_program",
                    "produced_objects": ["Main"],
                    "state_diff": {"changed": True, "added": ["Main"]},
                },
            }
        ],
        soft_plan=_plan(),
        phase_state={"phase_id": "P1", "status": "awaiting_execution", "attempt": 1},
        plan_mode=True,
        vision_enabled=False,
    )

    assert "宿主阶段门闩" in captured["user"]
    assert "[FAIL] valid_shape Main" in captured["user"]
    assert result["phase_state"]["status"] == "failed"
    assert result["soft_plan"]["items"][0]["status"] == "in_progress"
    assert result["soft_plan"]["items"][1]["status"] == "pending"
