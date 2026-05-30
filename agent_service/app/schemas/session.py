from pydantic import BaseModel, Field
from typing import Optional


class Phase(BaseModel):
    """A high-level phase in the modeling plan."""
    phase_id: str = Field(..., description="Phase identifier (P1, P2, ...)")
    title: str = Field(..., description="Phase title")
    intent: str = Field(..., description="What this phase should accomplish")
    success_criteria: list[str] = Field(
        default_factory=list, description="Criteria to judge phase success"
    )


class HighLevelPlan(BaseModel):
    """High-level modeling plan (phase-level, not tool-level)."""
    goal: str = Field(..., description="Overall modeling goal")
    phases: list[Phase] = Field(default_factory=list, description="Modeling phases")
    assumptions: list[str] = Field(default_factory=list, description="Assumptions made")


class SessionSummary(BaseModel):
    """Summary of session state sent from FreeCAD to Agent."""
    session_id: str
    user_input: str
    high_level_plan: HighLevelPlan
    current_phase_id: str
    execution_history: dict = Field(
        default_factory=dict,
        description="Recent results + older status counts"
    )
    name_map: dict[str, str] = Field(
        default_factory=dict,
        description="Object name mappings (Base -> Base_Fillet)"
    )


class ToolCall(BaseModel):
    """A single tool call in a plan or next_step response."""
    call_id: str = Field(..., description="Call identifier (P1_S1, P1_S2, ...)")
    tool: str = Field(..., description="Tool name")
    args: dict = Field(default_factory=dict, description="Tool arguments")
    description: str = Field("", description="What this call does")
    expected_effect: Optional[dict] = Field(
        None, description="Expected result (new_object, type, bbox_approx, etc.)"
    )


class ExecutionResult(BaseModel):
    """Result of executing a tool call."""
    call_id: str
    status: str = Field(..., description="success / error")
    tool: str
    args: dict = Field(default_factory=dict)
    resolved_args: dict = Field(default_factory=dict)
    produced_objects: list[str] = Field(default_factory=list)
    source_objects: list[str] = Field(default_factory=list)
    name_map_update: dict[str, str] = Field(default_factory=dict)
    message: Optional[str] = None


class HistoryEntry(BaseModel):
    """Entry in execution history."""
    call_id: str
    tool: str
    status: str
    produced_objects: list[str] = Field(default_factory=list)
    name_map_update: dict[str, str] = Field(default_factory=dict)
    message: Optional[str] = None
