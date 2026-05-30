import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import VERSION
from app.schemas.request import (
    PlanRequest,
    StartPlanRequest,
    NextStepRequest,
    EvaluateStepRequest,
    LogExecutionRequest,
)
from app.schemas.response import (
    PlanResponse,
    HealthResponse,
    StartPlanResponse,
    NextStepResponse,
    EvaluateStepResponse,
)
from app.graph.cad_graph import (
    get_cad_agent,
    get_start_plan_agent,
    get_next_step_agent,
    get_evaluate_agent,
)
from app.graph.nodes import _sanitize_tool_calls
from app.debug.middleware import trace_api_step, attach_debug_fields
from app.debug.trace_logger import TraceSession, is_debug_enabled

app = FastAPI(
    title="NL-FreeCAD-Agent",
    version=VERSION,
    description="Natural language driven FreeCAD feature tree modeling agent",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _base_state(**overrides) -> dict:
    """Build a complete AgentState dict with defaults."""
    state = {
        "user_input": "",
        "document_state": None,
        "plan_json": None,
        "status": "",
        "error_message": None,
        "conversation_id": None,
        "retry_count": 0,
        "validation_errors": [],
        "high_level_plan": None,
        "phases": None,
        "current_phase_id": None,
        "session_id": None,
        "execution_history": None,
        "name_map": None,
        "next_step_result": None,
        "last_tool_call": None,
        "execution_result": None,
        "evaluate_result": None,
    }
    state.update(overrides)
    return state


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", version=VERSION)


@app.post("/agent/plan")
async def plan(request: PlanRequest):
    """Generate a modeling plan via LangGraph pipeline (parse → plan → validate → retry)."""
    agent = get_cad_agent()

    input_state = _base_state(
        user_input=request.user_input,
        document_state=request.document_state,
        conversation_id=request.conversation_id,
    )

    final_state = agent.invoke(input_state)

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
    """Generate a high-level phase plan (V0.7 closed-loop architecture)."""
    agent = get_start_plan_agent()
    session_id = f"session_{uuid.uuid4().hex[:8]}"
    payload = request.model_dump(mode="json")

    with trace_api_step(
        session_id, "start_plan", payload, request.debug_mode, create_new=True
    ) as (trace, step_name):
        final_state = agent.invoke(_base_state(
            user_input=request.user_input,
            document_state=request.document_state,
        ))

        status = final_state.get("status", "error")
        high_level_plan = final_state.get("high_level_plan")

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
            if trace and step_name:
                trace.log_api_response(step_name, response.model_dump(mode="json"))
            return attach_debug_fields(response, trace, step_name)

        if status != "ok" or not high_level_plan:
            response = StartPlanResponse(
                status="error",
                session_id=session_id,
                user_input=request.user_input,
                message=final_state.get("error_message", "生成高层计划失败"),
            )
            if trace and step_name:
                trace.log_api_response(step_name, response.model_dump(mode="json"))
            return attach_debug_fields(response, trace, step_name)

        response = StartPlanResponse(
            status="ok",
            session_id=session_id,
            user_input=request.user_input,
            goal=high_level_plan.get("goal", ""),
            phases=high_level_plan.get("phases", []),
            assumptions=high_level_plan.get("assumptions", []),
        )
        if trace and step_name:
            trace.log_api_response(step_name, response.model_dump(mode="json"))
        return attach_debug_fields(response, trace, step_name)


@app.post("/agent/next_step", response_model=NextStepResponse)
async def next_step(request: NextStepRequest):
    """Generate next tool call(s) based on current state and history."""
    agent = get_next_step_agent()
    payload = request.model_dump(mode="json")

    with trace_api_step(
        request.session_id,
        "next_step",
        payload,
        request.debug_mode,
        phase_id=request.current_phase_id,
    ) as (trace, step_name):
        final_state = agent.invoke(_base_state(
            user_input=request.user_input,
            document_state=request.document_state,
            session_id=request.session_id,
            high_level_plan=request.high_level_plan,
            current_phase_id=request.current_phase_id,
            execution_history=request.execution_history,
            name_map=request.name_map,
        ))

        next_step_result = final_state.get("next_step_result", {})
        status = final_state.get("status", "")

        if status == "validation_failed":
            response = NextStepResponse(
                decision="abort",
                phase_id=request.current_phase_id,
                message=final_state.get("error_message", "工具调用校验失败"),
            )
            if trace and step_name:
                trace.log_api_response(step_name, response.model_dump(mode="json"))
            return attach_debug_fields(response, trace, step_name)

        response = NextStepResponse(
            decision=next_step_result.get("decision", "execute"),
            phase_id=next_step_result.get("phase_id", request.current_phase_id),
            tool_calls=_sanitize_tool_calls(next_step_result.get("tool_calls", []), prefix="step"),
            message=next_step_result.get("message"),
            question=next_step_result.get("question"),
        )
        if trace and step_name:
            trace.log_api_response(step_name, response.model_dump(mode="json"))
        return attach_debug_fields(response, trace, step_name)


@app.post("/agent/evaluate_step", response_model=EvaluateStepResponse)
async def evaluate_step(request: EvaluateStepRequest):
    """Evaluate execution result and decide next action."""
    agent = get_evaluate_agent()
    payload = request.model_dump(mode="json")
    call_id = request.last_tool_call.get("call_id")

    with trace_api_step(
        request.session_id,
        "evaluate_step",
        payload,
        request.debug_mode,
        phase_id=request.current_phase_id,
        call_id=call_id,
    ) as (trace, step_name):
        if trace and step_name:
            trace.log_execution(
                step_name,
                request.last_tool_call,
                request.execution_result,
                document_state=payload.get("document_state"),
            )

        final_state = agent.invoke(_base_state(
            session_id=request.session_id,
            last_tool_call=request.last_tool_call,
            execution_result=request.execution_result,
            document_state=request.document_state,
            execution_history=request.execution_history,
            high_level_plan=request.high_level_plan,
            current_phase_id=request.current_phase_id,
        ))

        evaluate_result = final_state.get("evaluate_result", {})

        response = EvaluateStepResponse(
            decision=evaluate_result.get("decision", "continue"),
            phase_status=evaluate_result.get("phase_status", "in_progress"),
            updated_current_phase_id=evaluate_result.get("updated_current_phase_id"),
            message=evaluate_result.get("message"),
            repair_tool_calls=_sanitize_tool_calls(
                evaluate_result.get("repair_tool_calls", [])
            ),
            deterministic_issues=evaluate_result.get("deterministic_issues", []),
        )
        if trace and step_name:
            trace.log_api_response(step_name, response.model_dump(mode="json"))
        return attach_debug_fields(response, trace, step_name)


@app.post("/agent/log_execution")
async def log_execution(request: LogExecutionRequest):
    """Log FreeCAD tool execution into an existing trace step folder."""
    if not is_debug_enabled(request.debug_mode):
        return {"status": "skipped", "reason": "debug disabled"}

    trace = TraceSession.open_existing(request.session_id)
    if trace is None:
        return {"status": "error", "reason": "trace session not found"}

    trace.log_execution(
        request.step_name,
        request.tool_call,
        request.execution_result,
        document_state=(
            request.document_state.model_dump(mode="json")
            if request.document_state is not None
            else None
        ),
    )
    return {
        "status": "ok",
        "debug_session_path": trace.path,
        "debug_step_name": request.step_name,
    }
