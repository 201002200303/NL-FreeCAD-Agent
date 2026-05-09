from pydantic import BaseModel, Field
from typing import Any, Optional
from app.schemas.cad_plan import PlanStep


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


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
