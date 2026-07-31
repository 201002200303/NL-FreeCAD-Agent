"""V0.8 harness helpers: abstract-step advancement and global validators."""

from __future__ import annotations

from app.abstract_steps.planner import advance_step_queue
from app.abstract_steps.schemas import AbstractStepQueue

DEFAULT_VALIDATORS: list[str] = []


def resolve_validator_names(
    current_abstract_step: dict | None,
    current_recipe: dict | None = None,
) -> list[str]:
    """Resolve optional strict geometry validators for the current step."""
    if current_abstract_step:
        names = [
            name
            for name in current_abstract_step.get("postconditions", [])
            if name.startswith("verify_")
        ]
        if names:
            return names
    if current_recipe:
        names = list(current_recipe.get("validators", []))
        if names:
            return names
    return list(DEFAULT_VALIDATORS)


def should_advance_abstract_step(
    *,
    execution_passed: bool,
    validator_results: list[dict],
) -> bool:
    """Default advancement depends only on tool execution success."""
    return bool(execution_passed)


def apply_abstract_step_advancement(
    abstract_step_queue: dict,
    completed_step_id: str,
) -> dict:
    """Mark one abstract step complete and return updated queue + next step."""
    queue = AbstractStepQueue(**abstract_step_queue)
    updated = advance_step_queue(queue, completed_step_id)
    next_step = updated.current_step()
    return {
        "abstract_step_queue": updated.model_dump(mode="json"),
        "current_abstract_step": next_step.model_dump(mode="json") if next_step else None,
        "queue_completed": updated.current_step_id is None,
        "updated_current_phase_id": next_step.step_id if next_step else None,
    }
