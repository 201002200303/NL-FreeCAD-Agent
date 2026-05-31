from typing import Any, Optional

from pydantic import BaseModel, Field


class CADFeature(BaseModel):
    """A structured user-intent feature, not a FreeCAD tool call."""

    type: str = Field(..., description="Feature type, such as box, cylinder, hole, fillet")
    name_hint: Optional[str] = Field(default=None)
    dimensions: dict[str, float] = Field(default_factory=dict)
    position: Optional[str] = Field(default=None)
    target_hint: Optional[str] = Field(default=None)
    parameters: dict[str, Any] = Field(default_factory=dict)


class CADSpec(BaseModel):
    """Structured CAD requirement. It must not contain tool calls."""

    model_type: str = Field(default="generic")
    unit: str = Field(default="mm")
    coordinate_system: str = Field(default="XYZ")
    features: list[CADFeature] = Field(default_factory=list)
    dimensions: dict[str, float] = Field(default_factory=dict)
    unknowns: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class SpecGenerationResult(BaseModel):
    status: str = Field(default="ok", description="ok / need_more_info / error")
    user_input: str = Field(default="")
    cad_spec: Optional[CADSpec] = None
    question: Optional[str] = None
    message: Optional[str] = None

