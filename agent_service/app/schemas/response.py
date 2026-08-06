from pydantic import BaseModel, Field
from typing import Any, Optional

from app.schemas.session import ToolCall


class HealthResponse(BaseModel):
    status: str = Field(default="ok")
    version: str = Field(default="0.1.0")


class SessionSnapshotResponse(BaseModel):
    status: str = Field(default="ok")
    session_id: str = Field(default="")
    session_status: Optional[str] = Field(default=None)
    user_input: Optional[str] = Field(default=None)
    user_goal: Optional[str] = Field(default=None)
    checkpoint_id: Optional[str] = Field(default=None)
    run_state: dict = Field(default_factory=dict)
    recent_events: list[dict] = Field(default_factory=list)
    completed_action_ids: list[str] = Field(default_factory=list)
    message: Optional[str] = Field(default=None)


class SessionListResponse(BaseModel):
    status: str = Field(default="ok")
    sessions: list[dict] = Field(default_factory=list)


class PauseSessionResponse(BaseModel):
    status: str = Field(default="ok")
    session_id: str = Field(default="")
    checkpoint_id: Optional[str] = Field(default=None)
    message: Optional[str] = Field(default=None)


class ResumeSessionResponse(BaseModel):
    status: str = Field(default="ok")
    session_id: str = Field(default="")
    checkpoint_id: Optional[str] = Field(default=None)
    run_state: dict = Field(default_factory=dict)
    document_changes: Optional[dict] = Field(default=None)
    events_replayed: int = Field(default=0)
    message: Optional[str] = Field(default=None)


class ChatResponse(BaseModel):
    status: str = Field(
        ...,
        description="awaiting_tools / awaiting_user / done / error",
    )
    session_id: str = Field(default="")
    message: str = Field(default="", description="给用户看的自然语言回复")
    question: Optional[str] = Field(default=None)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    soft_plan: Optional[dict] = Field(default=None)
    vision_memory: Optional[dict] = Field(
        default=None, description="视觉主线状态（客户端回传并更新）"
    )
    plan_mode: bool = Field(default=True)
    vision_enabled: bool = Field(default=False)
    vision: Optional[dict] = Field(default=None, description="本轮视觉检查结果")
    context_chars: int = Field(default=0)
    turn_count: int = Field(default=0)
    debug_session_path: Optional[str] = Field(default=None)
    debug_step_name: Optional[str] = Field(default=None)


class CompressContextResponse(BaseModel):
    status: str = Field(default="ok")
    session_id: str = Field(default="")
    message: str = Field(default="")
    context_chars: int = Field(default=0)
    turn_count: int = Field(default=0)
    summary: Optional[str] = Field(default=None)


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
