from pydantic import BaseModel, Field
from typing import Optional


class ToolCall(BaseModel):
    """A single tool call returned by /agent/chat."""

    call_id: str = Field(..., description="Call identifier (T1, T2, ...)")
    tool: str = Field(..., description="Tool name")
    args: dict = Field(default_factory=dict, description="Tool arguments")
    description: str = Field("", description="What this call does")
    expected_effect: Optional[dict] = Field(
        None, description="Expected result (new_object, type, bbox_approx, etc.)"
    )
    blocked: Optional[bool] = Field(
        default=None, description="服务端预校验拒绝；客户端勿执行"
    )
    preflight_error: Optional[str] = Field(
        default=None, description="预校验失败原因（须回灌给模型）"
    )


class ExecutionResult(BaseModel):
    """Result of executing a tool call on the FreeCAD client."""

    call_id: str
    status: str = Field(..., description="success / error")
    tool: str
    args: dict = Field(default_factory=dict)
    resolved_args: dict = Field(default_factory=dict)
    produced_objects: list[str] = Field(default_factory=list)
    source_objects: list[str] = Field(default_factory=list)
    name_map_update: dict[str, str] = Field(default_factory=dict)
    message: Optional[str] = None
