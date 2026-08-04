"""
=============================================================================
FastAPI 教学示例 — 数据模型层 (schemas.py)
=============================================================================
定义所有请求/响应的"数据契约"。
每个继承 BaseModel 的类 = FastAPI 自动校验 + 生成 Swagger 文档的依据。

断点建议（调试数据流动时打在这里）:
  - 任何 BaseModel 的 Field(...) 定义处 → 看数据校验规则
  - 尤其关注 list[PlanStep] 这种嵌套类型 → 看 FastAPI 如何递归校验
=============================================================================
"""

from pydantic import BaseModel, Field
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════════════════════
# 请求模型 — 客户端 → 服务端
# ═══════════════════════════════════════════════════════════════════════════

class PlanRequest(BaseModel):
    """
    用户发起建模请求的 JSON 结构。

    curl 示例:
      curl -X POST http://127.0.0.1:8765/agent/plan \
        -H "Content-Type: application/json" \
        -d '{"user_input": "画一个 100x60x20mm 的底座"}'

    FastAPI 收到请求后自动做的事:
      1. 读取 HTTP Body 原始字节
      2. Content-Type: application/json → JSON 解码
      3. PlanRequest(**decoded_dict) 构造对象
      4. 校验: user_input 必填? 是 str?
      5. 不通过 → 直接返回 422（函数不执行）
      6. 通过   → 把 PlanRequest 对象传给路由函数
    """
    user_input: str = Field(
        ...,
        description="用户的自然语言建模需求",
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description="会话 ID，用于多轮对话",
    )


class ExecuteRequest(BaseModel):
    """
    执行建模计划的请求，包含嵌套的 PlanStep 列表。
    这个类比 PlanRequest 复杂，用来演示 FastAPI 解析嵌套数据。

    FastAPI 会递归解析:
      ExecuteRequest
        └─ plan: list[PlanStep]
             ├─ PlanStep(step_id="S1", tool="create_box", ...)
             └─ PlanStep(step_id="S2", tool="create_cylinder", ...)
    """
    conversation_id: Optional[str] = Field(default=None)
    plan: list["PlanStep"] = Field(
        ...,
        description="建模步骤列表",
    )


# ═══════════════════════════════════════════════════════════════════════════
# 响应模型 — 服务端 → 客户端
# ═══════════════════════════════════════════════════════════════════════════

class HealthResponse(BaseModel):
    status: str = Field(default="ok")
    version: str = Field(default="0.1.0")


class PlanStep(BaseModel):
    """
    建模计划中的一个步骤。

    这个模型被两处复用:
      - PlanResponse.plan  → 服务端返回时包含
      - ExecuteRequest.plan → 客户端发送时包含

    default_factory=dict 而不是 default={}:
      避免所有实例共享同一个 dict 对象（Python 经典陷阱）
    """
    step_id: str = Field(..., description="步骤唯一标识，如 S1, S2")
    description: str = Field(..., description="人类可读的步骤描述")
    tool: str = Field(..., description="CAD 工具名称")
    args: dict[str, Any] = Field(default_factory=dict, description="工具参数")
    depends_on: list[str] = Field(default_factory=list, description="前置步骤 ID")


class PlanResponse(BaseModel):
    """
    建模计划响应 — 核心接口的返回值。

    响应 JSON 示例:
      {
        "status": "ok",
        "goal": "创建一个 100.0x60.0x20.0mm 的长方体",
        "assumptions": ["单位默认为 mm"],
        "missing_params": [],
        "question": null,
        "plan": [
          {"step_id": "S1", "description": "...", "tool": "create_box", ...}
        ]
      }
    """
    status: str = Field(..., description="ok 或 need_more_info")
    goal: str = Field(default="")
    assumptions: list[str] = Field(default_factory=list)
    missing_params: list[str] = Field(default_factory=list)
    question: Optional[str] = Field(default=None)
    plan: list[PlanStep] = Field(default_factory=list)


class ExecuteResponse(BaseModel):
    status: str = Field(..., description="success 或 partial_failure")
    results: list["StepResult"] = Field(default_factory=list)


class StepResult(BaseModel):
    step_id: str
    success: bool
    message: str


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None