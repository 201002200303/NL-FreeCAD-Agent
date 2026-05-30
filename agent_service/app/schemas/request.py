from pydantic import BaseModel, Field
from typing import Any, Optional
from app.schemas.cad_state import DocumentState


class PlanRequest(BaseModel):
    user_input: str = Field(..., description="Natural language modeling request")
    document_state: Optional[DocumentState] = Field(
        default=None, description="Current FreeCAD document state"
    )
    conversation_id: Optional[str] = Field(
        default=None, description="Conversation ID for multi-turn"
    )


class StartPlanRequest(BaseModel):
    user_input: str = Field(..., description="Natural language modeling request")
    document_state: Optional[DocumentState] = Field(
        default=None, description="Current FreeCAD document state"
    )
    debug_mode: bool = Field(default=False, description="Enable LLM trace logging")


class NextStepRequest(BaseModel):
    session_id: str = Field(..., description="Session identifier")
    user_input: str = Field(..., description="Original user request")
    high_level_plan: dict = Field(..., description="High-level phase plan")
    current_phase_id: Optional[str] = Field(default=None, description="Current phase ID")
    document_state: Optional[DocumentState] = Field(default=None)
    execution_history: dict = Field(default_factory=dict)
    name_map: dict[str, str] = Field(default_factory=dict)
    debug_mode: bool = Field(default=False, description="Enable LLM trace logging")


class EvaluateStepRequest(BaseModel):
    session_id: str = Field(..., description="Session identifier")
    last_tool_call: dict = Field(default_factory=dict)
    execution_result: dict = Field(default_factory=dict)
    document_state: Optional[DocumentState] = Field(default=None)
    execution_history: dict = Field(default_factory=dict)
    high_level_plan: dict = Field(default_factory=dict)
    current_phase_id: Optional[str] = Field(default=None)
    debug_mode: bool = Field(default=False, description="Enable LLM trace logging")


class LogExecutionRequest(BaseModel):
    session_id: str = Field(..., description="Session identifier")
    step_name: str = Field(..., description="Trace step folder name from prior response")
    tool_call: dict = Field(default_factory=dict)
    execution_result: dict = Field(default_factory=dict)
    document_state: Optional[DocumentState] = Field(default=None)
    debug_mode: bool = Field(default=False)
