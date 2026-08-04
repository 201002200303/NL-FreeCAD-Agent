"""HTTP layer only. All workflow logic lives in app.workflow.service."""
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import VERSION
from app.schemas.request import (
    PlanRequest,
    StartPlanRequest,
    NextStepRequest,
    EvaluateStepRequest,
    LogExecutionRequest,
    SpecRequest,
    ImpactMapRequest,
    SelectRecipeRequest,
    PauseSessionRequest,
    ResumeSessionRequest,
    ChatRequest,
    CompressContextRequest,
)
from app.schemas.response import (
    PlanResponse,
    HealthResponse,
    StartPlanResponse,
    NextStepResponse,
    EvaluateStepResponse,
    SpecResponse,
    ImpactMapResponse,
    SelectRecipeResponse,
    SessionSnapshotResponse,
    SessionListResponse,
    PauseSessionResponse,
    ResumeSessionResponse,
    ChatResponse,
    CompressContextResponse,
)
from app.workflow import service as workflow
from app.workflow import chat as chat_workflow
from app.conversation import conversation_scope
from app.conversation.notes import format_resume_note
from app import config as app_config
from app.vision import vision_available
from app.debug.middleware import trace_api_step, attach_debug_fields
from app.debug.trace_logger import TraceSession, is_debug_enabled
from app.cad_spec.generator import generate_cad_spec
from app.inspection.impact_map import build_impact_map
from app.recipes.registry import select_recipe as select_recipe_from_registry
from app.runtime import get_runtime


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
    with trace_api_step(
        sid, "chat", payload, request.debug_mode, create_new=create_new
    ) as (trace, step_name):
        result = chat_workflow.chat_turn(
            session_id=sid,
            message=request.message,
            document_state=request.document_state,
            tool_results=request.tool_results or None,
            viewport_image=(
                request.viewport_image.model_dump() if request.viewport_image else None
            ),
            plan_mode=request.plan_mode,
            vision_enabled=request.vision_enabled,
            session_memory=request.session_memory,
            name_map=request.name_map,
            soft_plan=request.soft_plan,
            user_goal=request.user_goal or request.message,
        )
        sid = result.get("session_id") or sid
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
    result = chat_workflow.compress_context(
        request.session_id, keep_recent_turns=request.keep_recent_turns
    )
    return CompressContextResponse(**result)


@app.post("/agent/spec", response_model=SpecResponse)
async def spec(request: SpecRequest):
    """Generate a V0.8 CAD Spec from natural language. No tool calls are emitted."""
    session_id = f"spec_{uuid.uuid4().hex[:8]}"
    payload = request.model_dump(mode="json")
    with trace_api_step(
        session_id, "spec", payload, request.debug_mode, create_new=True
    ) as (trace, step_name):
        result = generate_cad_spec(request.user_input)
        response = SpecResponse(**result.model_dump(mode="json"))
        if trace and step_name:
            trace.log_api_response(step_name, response.model_dump(mode="json"))
        return attach_debug_fields(response, trace, step_name)


@app.post("/agent/impact_map", response_model=ImpactMapResponse)
async def impact_map(request: ImpactMapRequest):
    """Build a V0.8 Model Impact Map from CAD Spec and current document state."""
    session_id = f"impact_{uuid.uuid4().hex[:8]}"
    payload = request.model_dump(mode="json")
    with trace_api_step(
        session_id, "impact_map", payload, request.debug_mode, create_new=True
    ) as (trace, step_name):
        result = build_impact_map(request.cad_spec, request.document_state)
        status = "blocked" if result.blocked else "ok"
        response = ImpactMapResponse(status=status, impact_map=result, message=result.block_reason)
        if trace and step_name:
            trace.log_api_response(step_name, response.model_dump(mode="json"))
        return attach_debug_fields(response, trace, step_name)


@app.post("/agent/select_recipe", response_model=SelectRecipeResponse)
async def select_recipe(request: SelectRecipeRequest):
    """Select a registered V0.8 recipe and expand it to an abstract step queue."""
    session_id = f"recipe_{uuid.uuid4().hex[:8]}"
    payload = request.model_dump(mode="json")
    with trace_api_step(
        session_id, "select_recipe", payload, request.debug_mode, create_new=True
    ) as (trace, step_name):
        result = select_recipe_from_registry(
            request.cad_spec,
            request.impact_map,
        )
        response = SelectRecipeResponse(**result)
        if trace and step_name:
            trace.log_api_response(step_name, response.model_dump(mode="json"))
        return attach_debug_fields(response, trace, step_name)


@app.post("/agent/plan")
async def plan(request: PlanRequest):
    """Legacy V0.1 one-shot plan (kept; not part of the closed loop)."""
    final_state = workflow.legacy_plan(
        user_input=request.user_input,
        document_state=request.document_state,
        conversation_id=request.conversation_id,
    )
    plan_json = final_state.get("plan_json")
    status = final_state.get("status", "error")
    if not plan_json:
        return PlanResponse(
            status="error",
            goal="计划生成失败",
            assumptions=[],
            missing_params=[],
            question=final_state.get("error_message", "未知错误"),
            plan=[],
        )
    if status == "validation_failed":
        plan_json["status"] = "error"
        plan_json.setdefault("question", final_state.get("error_message"))
    return PlanResponse(**plan_json)


@app.post("/agent/start_plan", response_model=StartPlanResponse)
async def start_plan(request: StartPlanRequest):
    session_id = f"session_{uuid.uuid4().hex[:8]}"
    payload = request.model_dump(mode="json")
    with trace_api_step(
        session_id, "start_plan", payload, request.debug_mode, create_new=True
    ) as (trace, step_name), conversation_scope(session_id):
        result = workflow.start_plan(
            user_input=request.user_input,
            document_state=request.document_state,
        )
        status = result.get("status", "error")
        high_level_plan = result.get("high_level_plan")

        if status == "need_more_info" and high_level_plan:
            response = StartPlanResponse(
                status="need_more_info",
                session_id=session_id,
                user_input=request.user_input,
                goal=high_level_plan.get("goal", ""),
                phases=high_level_plan.get("phases", []),
                assumptions=high_level_plan.get("assumptions", []),
                question=high_level_plan.get("question"),
            )
        elif status != "ok" or not high_level_plan:
            response = StartPlanResponse(
                status="error",
                session_id=session_id,
                user_input=request.user_input,
                message=result.get("error_message", "生成高层计划失败"),
            )
        else:
            response = StartPlanResponse(
                status="ok",
                session_id=session_id,
                user_input=request.user_input,
                goal=high_level_plan.get("goal", ""),
                phases=high_level_plan.get("phases", []),
                assumptions=high_level_plan.get("assumptions", []),
                abstract_step_queue=result.get("abstract_step_queue"),
                current_abstract_step=result.get("current_abstract_step"),
            )
            try:
                get_runtime().start_session(
                    session_id,
                    user_input=request.user_input,
                    goal=high_level_plan.get("goal", ""),
                    plan={
                        **high_level_plan,
                        "abstract_step_queue": result.get("abstract_step_queue"),
                        "current_abstract_step": result.get("current_abstract_step"),
                    },
                    document_state=_dump_doc(request.document_state),
                )
            except Exception as exc:
                print(f"[runtime] start_session failed: {exc}")

        if trace and step_name:
            trace.log_api_response(step_name, response.model_dump(mode="json"))
        return attach_debug_fields(response, trace, step_name)


@app.post("/agent/next_step", response_model=NextStepResponse)
async def next_step(request: NextStepRequest):
    payload = request.model_dump(mode="json")
    with trace_api_step(
        request.session_id,
        "next_step",
        payload,
        request.debug_mode,
        phase_id=request.current_phase_id,
    ) as (trace, step_name), conversation_scope(request.session_id):
        final_state = workflow.next_step(
            user_input=request.user_input,
            high_level_plan=request.high_level_plan,
            current_phase_id=request.current_phase_id,
            document_state=request.document_state,
            execution_history=request.execution_history,
            session_memory=request.session_memory,
            name_map=request.name_map,
            abstract_step_queue=request.abstract_step_queue,
            current_abstract_step=request.current_abstract_step,
            session_id=request.session_id,
        )
        next_step_result = final_state.get("next_step_result", {})
        status = final_state.get("status", "")

        if status == "validation_failed":
            response = NextStepResponse(
                decision="abort",
                phase_id=request.current_phase_id,
                message=final_state.get("error_message", "工具调用校验失败"),
            )
        else:
            response = NextStepResponse(
                decision=next_step_result.get("decision", "execute"),
                phase_id=next_step_result.get("phase_id", request.current_phase_id),
                tool_calls=workflow.sanitize_tool_calls(
                    next_step_result.get("tool_calls", []), prefix="step"
                ),
                message=next_step_result.get("message"),
                question=next_step_result.get("question"),
                recipe_id=next_step_result.get("recipe_id"),
                abstract_step_id=next_step_result.get("abstract_step_id"),
                current_recipe=next_step_result.get("current_recipe"),
                current_abstract_step=next_step_result.get("current_abstract_step"),
            )
            try:
                tool_calls = [
                    c.model_dump(mode="json") if hasattr(c, "model_dump") else c
                    for c in (response.tool_calls or [])
                ]
                get_runtime().record_next_step(
                    request.session_id,
                    phase_id=response.phase_id,
                    decision=response.decision,
                    tool_calls=tool_calls,
                    message=response.message,
                    current_abstract_step=response.current_abstract_step,
                    document_state=_dump_doc(request.document_state),
                )
            except Exception as exc:
                print(f"[runtime] record_next_step failed: {exc}")

        if trace and step_name:
            trace.log_api_response(step_name, response.model_dump(mode="json"))
        return attach_debug_fields(response, trace, step_name)


@app.post("/agent/evaluate_step", response_model=EvaluateStepResponse)
async def evaluate_step(request: EvaluateStepRequest):
    payload = request.model_dump(mode="json")
    call_id = request.last_tool_call.get("call_id")
    with trace_api_step(
        request.session_id,
        "evaluate_step",
        payload,
        request.debug_mode,
        phase_id=request.current_phase_id,
        call_id=call_id,
    ) as (trace, step_name), conversation_scope(request.session_id):
        if trace and step_name:
            trace.log_execution(
                step_name,
                request.last_tool_call,
                request.execution_result,
                document_state=payload.get("document_state"),
            )

        final_state = workflow.evaluate_step(
            session_id=request.session_id,
            last_tool_call=request.last_tool_call,
            execution_result=request.execution_result,
            document_state=request.document_state,
            execution_history=request.execution_history,
            session_memory=request.session_memory,
            high_level_plan=request.high_level_plan,
            current_phase_id=request.current_phase_id,
            cad_spec=request.cad_spec,
            impact_map=request.impact_map,
            current_recipe=request.current_recipe,
            current_abstract_step=request.current_abstract_step,
            abstract_step_queue=request.abstract_step_queue,
            before_state=request.before_state,
        )
        evaluate_result = final_state.get("evaluate_result", {})

        response = EvaluateStepResponse(
            decision=evaluate_result.get("decision", "continue"),
            phase_status=evaluate_result.get("phase_status", "in_progress"),
            updated_current_phase_id=evaluate_result.get("updated_current_phase_id"),
            message=evaluate_result.get("message"),
            repair_tool_calls=workflow.sanitize_tool_calls(
                evaluate_result.get("repair_tool_calls", [])
            ),
            deterministic_issues=evaluate_result.get("deterministic_issues", []),
            validator_results=evaluate_result.get("validator_results", []),
            postcondition_results=evaluate_result.get("postcondition_results", []),
            abstract_step_queue=evaluate_result.get("abstract_step_queue"),
            current_abstract_step=evaluate_result.get("current_abstract_step"),
            abstract_step_completed=evaluate_result.get("abstract_step_completed", False),
        )
        try:
            doc_dict = _dump_doc(request.document_state)
            get_runtime().record_tool_result(
                request.session_id,
                tool_call=request.last_tool_call,
                execution_result=request.execution_result,
                phase_id=request.current_phase_id,
                document_state=doc_dict,
            )
            get_runtime().record_evaluate(
                request.session_id,
                evaluate_result=evaluate_result,
                phase_id=request.current_phase_id,
                document_state=doc_dict,
                high_level_plan=request.high_level_plan,
                abstract_step_queue=response.abstract_step_queue,
                current_abstract_step=response.current_abstract_step,
                session_memory=request.session_memory,
                name_map=request.name_map,
            )
        except Exception as exc:
            print(f"[runtime] record_evaluate failed: {exc}")

        if trace and step_name:
            trace.log_api_response(step_name, response.model_dump(mode="json"))
        return attach_debug_fields(response, trace, step_name)


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
    # 让模型看见状态断层：否则它的消息流里还写着「我创建了 Body」，
    # 而用户可能已经手工把 Body 删了。
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
        "debug_session_path": trace.path,
        "debug_step_name": request.step_name,
    }
