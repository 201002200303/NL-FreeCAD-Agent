"""HTTP layer. Workflow logic lives in app.workflow.chat."""
import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config as app_config
from app.config import VERSION
from app.conversation import conversation_scope
from app.conversation.notes import format_resume_note
from app.debug.middleware import attach_debug_fields, trace_api_step
from app.debug.trace_logger import TraceSession, is_debug_enabled
from app.runtime import get_runtime
from app.schemas.request import (
    ChatRequest,
    CompressContextRequest,
    LogExecutionRequest,
    PauseSessionRequest,
    ResumeSessionRequest,
)
from app.schemas.response import (
    ChatResponse,
    CompressContextResponse,
    HealthResponse,
    PauseSessionResponse,
    ResumeSessionResponse,
    SessionListResponse,
    SessionSnapshotResponse,
)
from app.vision import vision_available
from app.workflow import chat as chat_workflow


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path("data").mkdir(parents=True, exist_ok=True)
    get_runtime()
    try:
        from app.db.database import init_db
        await init_db()
    except Exception as exc:
        print(f"[startup] init_db skipped/failed: {exc}")
    yield


app = FastAPI(
    title="NL-FreeCAD-Agent",
    version=VERSION,
    description="Natural language driven FreeCAD feature tree modeling agent",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _dump_doc(document_state):
    return (
        document_state.model_dump(mode="json")
        if document_state is not None
        else None
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", version=VERSION)


@app.get("/agent/capabilities")
async def capabilities():
    """客户端用来同步开关：视觉是否可用、默认 plan_mode 等。"""
    return {
        "version": VERSION,
        "chat": True,
        "plan_mode_default": app_config.CHAT_PLAN_MODE_DEFAULT,
        "vision": {
            "enabled": app_config.VISION_ENABLED,
            "available": vision_available(),
            "model": app_config.VISION_MODEL or None,
        },
        "conversation_budget_chars": app_config.CONVERSATION_BUDGET_CHARS,
    }


@app.post("/agent/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """对话式建模主入口。用户消息或工具结果 → 自然语言回复 + 可选 tool_calls。"""
    sid = request.session_id or f"session_{uuid.uuid4().hex[:8]}"
    payload = request.model_dump(mode="json")
    create_new = not bool(request.session_id)
    # 预分类（视觉硬伤在 chat_turn 内判定后写回 meta）
    prelim_kind = chat_workflow.classify_chat_step(
        message=request.message,
        tool_results=request.tool_results or None,
    )
    with trace_api_step(
        sid,
        "chat",
        payload,
        request.debug_mode,
        create_new=create_new,
        phase_id=prelim_kind,
    ) as (trace, step_name):
        # LLM 是同步阻塞调用；放进线程池，避免拖死整个 uvicorn 事件循环
        # （否则等待模型时 /health 与其它请求全部卡住，客户端表现为「没响应」）。
        result = await asyncio.to_thread(
            chat_workflow.chat_turn,
            session_id=sid,
            message=request.message,
            document_state=request.document_state,
            tool_results=request.tool_results or None,
            viewport_image=(
                request.viewport_image.model_dump() if request.viewport_image else None
            ),
            viewport_images=[
                v.model_dump() for v in (request.viewport_images or [])
            ]
            or None,
            plan_mode=request.plan_mode,
            vision_enabled=request.vision_enabled,
            session_memory=request.session_memory,
            name_map=request.name_map,
            soft_plan=request.soft_plan,
            user_goal=request.user_goal or request.message,
        )
        sid = result.get("session_id") or sid
        step_kind = result.get("step_kind") or prelim_kind
        if trace and step_name and step_kind:
            try:
                meta_path = Path(trace.path) / step_name / "meta.json"
                if meta_path.is_file():
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    meta["step_kind"] = step_kind
                    meta_path.write_text(
                        json.dumps(meta, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            except Exception:
                pass
        response = ChatResponse(
            status=result.get("status", "error"),
            session_id=sid,
            message=result.get("message", ""),
            question=result.get("question"),
            tool_calls=result.get("tool_calls") or [],
            soft_plan=result.get("soft_plan"),
            plan_mode=bool(result.get("plan_mode", True)),
            vision_enabled=bool(result.get("vision_enabled")),
            vision=result.get("vision"),
            context_chars=int(result.get("context_chars") or 0),
            turn_count=int(result.get("turn_count") or 0),
        )
        if create_new and response.status != "error":
            try:
                get_runtime().start_session(
                    response.session_id,
                    user_input=request.user_goal or request.message,
                    goal=(request.user_goal or request.message)[:80],
                    plan={"soft_plan": response.soft_plan},
                    document_state=_dump_doc(request.document_state),
                )
            except Exception as exc:
                print(f"[runtime] chat start_session failed: {exc}")
        if trace and step_name:
            trace.log_api_response(step_name, response.model_dump(mode="json"))
        return attach_debug_fields(response, trace, step_name)


@app.post("/agent/compress", response_model=CompressContextResponse)
async def compress(request: CompressContextRequest):
    result = await asyncio.to_thread(
        chat_workflow.compress_context,
        request.session_id,
        keep_recent_turns=request.keep_recent_turns,
    )
    return CompressContextResponse(**result)


@app.get("/agent/sessions", response_model=SessionListResponse)
async def list_sessions(limit: int = 20):
    try:
        sessions = get_runtime().list_sessions(limit=limit)
    except Exception:
        return SessionListResponse(status="error", sessions=[])
    return SessionListResponse(status="ok", sessions=sessions)


@app.get("/agent/session/{session_id}", response_model=SessionSnapshotResponse)
async def get_session(session_id: str):
    snapshot = get_runtime().get_session_snapshot(session_id)
    if snapshot is None:
        return SessionSnapshotResponse(
            status="error",
            session_id=session_id,
            message="session not found",
        )
    session = snapshot["session"]
    return SessionSnapshotResponse(
        status="ok",
        session_id=session_id,
        session_status=session.get("status"),
        user_input=session.get("user_input"),
        user_goal=session.get("user_goal"),
        checkpoint_id=snapshot.get("checkpoint_id"),
        run_state=snapshot.get("run_state") or {},
        recent_events=snapshot.get("recent_events") or [],
        completed_action_ids=snapshot.get("completed_action_ids") or [],
    )


@app.post("/agent/session/{session_id}/pause", response_model=PauseSessionResponse)
async def pause_session(session_id: str, request: PauseSessionRequest):
    try:
        checkpoint = get_runtime().pause_session(
            session_id,
            document_state=_dump_doc(request.document_state),
            reason=request.reason,
        )
    except Exception as exc:
        return PauseSessionResponse(
            status="error", session_id=session_id, message=str(exc)
        )
    return PauseSessionResponse(
        status="ok",
        session_id=session_id,
        checkpoint_id=checkpoint.get("checkpoint_id"),
    )


@app.post("/agent/session/{session_id}/resume", response_model=ResumeSessionResponse)
async def resume_session(session_id: str, request: ResumeSessionRequest):
    try:
        result = get_runtime().resume_session(
            session_id, document_state=_dump_doc(request.document_state)
        )
    except Exception as exc:
        return ResumeSessionResponse(
            status="error", session_id=session_id, message=str(exc)
        )
    changes = result.get("document_changes")
    if note := format_resume_note(changes):
        with conversation_scope(session_id) as transcript:
            if transcript is not None:
                transcript.append_note(note)

    return ResumeSessionResponse(
        status="ok",
        session_id=session_id,
        checkpoint_id=result.get("checkpoint_id"),
        run_state=result.get("run_state") or {},
        document_changes=changes,
        events_replayed=result.get("events_replayed", 0),
        message=(changes or {}).get("summary") if changes else None,
    )


@app.post("/agent/log_execution")
async def log_execution(request: LogExecutionRequest):
    if not is_debug_enabled(request.debug_mode):
        return {"status": "skipped", "reason": "debug disabled"}
    trace = TraceSession.open_existing(request.session_id)
    if trace is None:
        return {"status": "error", "reason": "trace session not found"}
    trace.log_execution(
        request.step_name,
        request.tool_call,
        request.execution_result,
        document_state=_dump_doc(request.document_state),
    )
    try:
        get_runtime().record_tool_result(
            request.session_id,
            tool_call=request.tool_call,
            execution_result=request.execution_result,
            document_state=_dump_doc(request.document_state),
        )
    except Exception as exc:
        print(f"[runtime] log_execution event failed: {exc}")
    return {
        "status": "ok",
        "debug_session_path": str(trace.path),
    }
