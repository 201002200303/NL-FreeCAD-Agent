from pydantic import BaseModel, Field
from typing import Any


class ToolParameter(BaseModel):
    type: str = Field(..., description="Parameter type: string, float, int, bool")
    description: str = Field(default="", description="Parameter description")
    default: Any = Field(default=None, description="Default value")
    required: bool = Field(default=False)


class ToolSpec(BaseModel):
    description: str = Field(..., description="Tool description")
    parameters: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Parameter name -> parameter definition"
    )
    required: list[str] = Field(default_factory=list, description="Required parameter names")
