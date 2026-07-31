from pydantic import BaseModel, Field


class AbstractStep(BaseModel):
    step_id: str
    step_type: str
    intent: str
    input_refs: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    allowed_tool_categories: list[str] = Field(
        default_factory=list,
        description="Optional category hint; empty list means all registered tools are allowed",
    )
    max_retry: int = 2
    risk_level: str = Field(default="low")
    status: str = Field(default="pending")


class AbstractStepQueue(BaseModel):
    recipe_id: str
    steps: list[AbstractStep] = Field(default_factory=list)
    current_step_id: str | None = None

    def current_step(self) -> AbstractStep | None:
        if self.current_step_id:
            for step in self.steps:
                if step.step_id == self.current_step_id:
                    return step
        return self.steps[0] if self.steps else None

