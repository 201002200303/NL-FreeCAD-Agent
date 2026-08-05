from pydantic import BaseModel, Field
from typing import Optional

from app.schemas.cad_state import DocumentState


class PauseSessionRequest(BaseModel):
    document_state: Optional[DocumentState] = Field(default=None)
    reason: str = Field(default="", description="Why the user paused")


class ResumeSessionRequest(BaseModel):
    document_state: Optional[DocumentState] = Field(default=None)


class LogExecutionRequest(BaseModel):
    session_id: str = Field(..., description="Session identifier")
    step_name: str = Field(..., description="Trace step folder name from prior response")
    tool_call: dict = Field(default_factory=dict)
    execution_result: dict = Field(default_factory=dict)
    document_state: Optional[DocumentState] = Field(default=None)
    debug_mode: bool = Field(default=False)


class ViewportImage(BaseModel):
    image_b64: str = Field(..., description="Base64-encoded viewport screenshot")
    mime: str = Field(default="image/png")
    name: str = Field(default="viewport", description="视图名：front/side/top/iso")


class ChatRequest(BaseModel):
    """对话式建模：一个窗口、一个文档、一条上下文。"""

    session_id: Optional[str] = Field(default=None, description="空则新建会话")
    message: str = Field(default="", description="用户本轮输入；回传工具结果时可为空")
    document_state: Optional[DocumentState] = Field(default=None)
    tool_results: list[dict] = Field(
        default_factory=list,
        description="客户端执行完 tool_calls 后回传 [{tool_call, execution_result}]",
    )
    viewport_image: Optional[ViewportImage] = Field(
        default=None, description="可选单张视口截图（兼容旧客户端）"
    )
    viewport_images: list[ViewportImage] = Field(
        default_factory=list,
        description="可选多视图截图 front/side/top/iso，优先于 viewport_image",
    )
    plan_mode: Optional[bool] = Field(default=None, description="是否维护 soft_plan")
    vision_enabled: Optional[bool] = Field(
        default=None, description="本轮是否尝试视觉；仍受服务端 VISION_ENABLED 约束"
    )
    session_memory: Optional[dict] = Field(default=None)
    name_map: dict[str, str] = Field(default_factory=dict)
    soft_plan: Optional[dict] = Field(default=None, description="客户端持有的当前 todo")
    user_goal: str = Field(default="", description="会话最初需求摘要")
    debug_mode: bool = Field(default=False)


class CompressContextRequest(BaseModel):
    session_id: str
    keep_recent_turns: int = Field(default=4, ge=1, le=40)
    debug_mode: bool = Field(default=False)
