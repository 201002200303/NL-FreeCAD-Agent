"""Host-owned Phase Program lifecycle.

The Agent proposes a soft plan and CAD code.  This Module owns the control
truth: program identity, deterministic acceptance, and phase advancement.
"""

from app.phase_program.orchestrator import (
    PhaseReduction,
    format_phase_feedback,
    mark_current_phase,
    prepare_phase_tool_calls,
    reconcile_soft_plan,
    reduce_phase_feedback,
)

__all__ = [
    "PhaseReduction",
    "format_phase_feedback",
    "mark_current_phase",
    "prepare_phase_tool_calls",
    "reconcile_soft_plan",
    "reduce_phase_feedback",
]

