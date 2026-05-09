from pydantic import BaseModel, Field
from typing import Any, Optional


class ExpectedResult(BaseModel):
    object: str = Field(..., description="Expected resulting object name")
    type: str = Field(..., description="Expected FreeCAD object type")


class PlanStep(BaseModel):
    step_id: str = Field(..., description="Unique step identifier, e.g. S1, S2")
    description: str = Field(..., description="Human-readable step description")
    tool: str = Field(..., description="CAD Tool name")
    args: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    depends_on: list[str] = Field(
        default_factory=list, description="Step IDs this step depends on"
    )
    expected_result: Optional[ExpectedResult] = Field(
        default=None, description="Expected result after execution"
    )


class ModelingPlan(BaseModel):
    status: str = Field(..., description="Plan status: ok or need_more_info")
    goal: str = Field(default="", description="One-line modeling goal")
    assumptions: list[str] = Field(default_factory=list, description="Agent assumptions")
    missing_params: list[str] = Field(
        default_factory=list, description="Missing parameter names"
    )
    question: Optional[str] = Field(
        default=None, description="Clarification question when missing_params is non-empty"
    )
    plan: list[PlanStep] = Field(
        default_factory=list, description="Ordered modeling steps"
    )
