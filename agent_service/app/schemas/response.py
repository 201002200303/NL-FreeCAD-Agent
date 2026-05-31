from pydantic import BaseModel, Field
from typing import Any, Optional
from app.schemas.cad_plan import PlanStep
from app.schemas.session import Phase, ToolCall
from app.cad_spec.schemas import CADSpec
from app.inspection.impact_map import ImpactMap


class HealthResponse(BaseModel):
    status: str = Field(default="ok")
    version: str = Field(default="0.1.0")


class PlanResponse(BaseModel):
    status: str = Field(..., description="ok or need_more_info")
    goal: str = Field(default="")
    assumptions: list[str] = Field(default_factory=list)
    missing_params: list[str] = Field(default_factory=list)
    question: Optional[str] = Field(default=None)
    plan: list[PlanStep] = Field(default_factory=list)


class StartPlanResponse(BaseModel):
    status: str = Field(..., description="ok or need_more_info or error")
    session_id: Optional[str] = Field(default=None)
    user_input: str = Field(default="")
    goal: str = Field(default="")
    phases: list[Phase] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    question: Optional[str] = Field(default=None)
    message: Optional[str] = Field(default=None)
    cad_spec: Optional[CADSpec] = Field(default=None)
    impact_map: Optional[dict] = Field(default=None)
    current_recipe: Optional[dict] = Field(default=None)
    abstract_step_queue: Optional[dict] = Field(default=None)
    current_abstract_step: Optional[dict] = Field(default=None)
    debug_session_path: Optional[str] = Field(default=None)
    debug_step_name: Optional[str] = Field(default=None)


class NextStepResponse(BaseModel):
    decision: str = Field(..., description="execute / ask_user / repair / replan / finish / abort")
    phase_id: Optional[str] = Field(default=None)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    message: Optional[str] = Field(default=None)
    question: Optional[str] = Field(default=None)
    recipe_id: Optional[str] = Field(default=None)
    abstract_step_id: Optional[str] = Field(default=None)
    current_recipe: Optional[dict] = Field(default=None)
    current_abstract_step: Optional[dict] = Field(default=None)
    debug_session_path: Optional[str] = Field(default=None)
    debug_step_name: Optional[str] = Field(default=None)


class EvaluateStepResponse(BaseModel):
    decision: str = Field(
        ...,
        description="continue / repair / skip_and_continue / replan / finish / abort",
    )
    phase_status: str = Field(default="in_progress")
    updated_current_phase_id: Optional[str] = Field(default=None)
    message: Optional[str] = Field(default=None)
    repair_tool_calls: list[ToolCall] = Field(default_factory=list)
    deterministic_issues: list[str] = Field(default_factory=list)
    validator_results: list[dict] = Field(default_factory=list)
    postcondition_results: list[dict] = Field(default_factory=list)
    abstract_step_queue: Optional[dict] = Field(default=None)
    current_abstract_step: Optional[dict] = Field(default=None)
    abstract_step_completed: bool = Field(default=False)
    debug_session_path: Optional[str] = Field(default=None)
    debug_step_name: Optional[str] = Field(default=None)


class SpecResponse(BaseModel):
    status: str = Field(default="ok")
    user_input: str = Field(default="")
    cad_spec: Optional[CADSpec] = None
    question: Optional[str] = None
    message: Optional[str] = None
    debug_session_path: Optional[str] = Field(default=None)
    debug_step_name: Optional[str] = Field(default=None)


class ImpactMapResponse(BaseModel):
    status: str = Field(default="ok")
    impact_map: ImpactMap
    message: Optional[str] = None
    debug_session_path: Optional[str] = Field(default=None)
    debug_step_name: Optional[str] = Field(default=None)


class SelectRecipeResponse(BaseModel):
    status: str = Field(default="ok")
    recipe: Optional[dict] = None
    abstract_step_queue: Optional[dict] = None
    message: Optional[str] = None
    debug_session_path: Optional[str] = Field(default=None)
    debug_step_name: Optional[str] = Field(default=None)


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
