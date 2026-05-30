"""
LangGraph graph builders for the CAD Agent workflow.

V0.1-V0.6:
  build_cad_graph() — parse_input → plan → validate_plan → (conditional)

V0.7 (closed-loop architecture):
  build_start_plan_graph()  — parse_input → generate_high_level_plan → validate → END
  build_next_step_graph()   — plan_next_step → validate_next_step → END
  build_evaluate_graph()    — evaluate_step → END
"""

from langgraph.graph import StateGraph, END
from app.graph.state import AgentState
from app.graph.nodes import (
    parse_input_node, plan_node, validate_plan_node, should_end,
    generate_high_level_plan_node, validate_high_level_plan_node,
    plan_next_step_node, validate_next_step_node,
    evaluate_step_node,
)


def _increment_retry(state: AgentState) -> dict:
    """Increment retry count before re-entering plan_node."""
    return {"retry_count": state.get("retry_count", 0) + 1}


# ── V0.1-V0.6: Original plan graph ────────────────────────────────


def build_cad_graph() -> StateGraph:
    """Build the original CAD Agent plan generation graph."""
    workflow = StateGraph(AgentState)

    workflow.add_node("parse_input", parse_input_node)
    workflow.add_node("plan", plan_node)
    workflow.add_node("validate_plan", validate_plan_node)
    workflow.add_node("retry_bump", _increment_retry)

    workflow.set_entry_point("parse_input")
    workflow.add_edge("parse_input", "plan")
    workflow.add_edge("plan", "validate_plan")

    workflow.add_conditional_edges(
        "validate_plan",
        should_end,
        {
            "end": END,
            "retry": "retry_bump",
        },
    )

    workflow.add_edge("retry_bump", "plan")

    return workflow


# ── V0.7: Start plan graph ─────────────────────────────────────────


def _should_end_high_level(state: AgentState) -> str:
    """Routing after high-level plan validation."""
    status = state.get("status", "")
    if status in ("ok", "need_more_info", "error"):
        return "end"
    return "end"


def build_start_plan_graph() -> StateGraph:
    """Build the high-level plan generation graph.

    Flow: parse_input → generate_high_level_plan → validate_high_level_plan → END
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("parse_input", parse_input_node)
    workflow.add_node("generate_high_level_plan", generate_high_level_plan_node)
    workflow.add_node("validate_high_level_plan", validate_high_level_plan_node)

    workflow.set_entry_point("parse_input")
    workflow.add_edge("parse_input", "generate_high_level_plan")
    workflow.add_edge("generate_high_level_plan", "validate_high_level_plan")
    workflow.add_edge("validate_high_level_plan", END)

    return workflow


# ── V0.7: Next step graph ──────────────────────────────────────────


def build_next_step_graph() -> StateGraph:
    """Build the next step planning graph.

    Flow: plan_next_step → validate_next_step → END
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("plan_next_step", plan_next_step_node)
    workflow.add_node("validate_next_step", validate_next_step_node)

    workflow.set_entry_point("plan_next_step")
    workflow.add_edge("plan_next_step", "validate_next_step")
    workflow.add_edge("validate_next_step", END)

    return workflow


# ── V0.7: Evaluate graph ───────────────────────────────────────────


def build_evaluate_graph() -> StateGraph:
    """Build the step evaluation graph.

    Flow: evaluate_step → END
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("evaluate_step", evaluate_step_node)

    workflow.set_entry_point("evaluate_step")
    workflow.add_edge("evaluate_step", END)

    return workflow


# ── Singleton compiled graphs ──────────────────────────────────────


_compiled_agent = None
_compiled_start_plan = None
_compiled_next_step = None
_compiled_evaluate = None


def get_cad_agent():
    """Get or create the compiled CAD Agent plan graph (singleton)."""
    global _compiled_agent
    if _compiled_agent is None:
        _compiled_agent = build_cad_graph().compile()
    return _compiled_agent


def get_start_plan_agent():
    """Get or create the compiled start_plan graph (singleton)."""
    global _compiled_start_plan
    if _compiled_start_plan is None:
        _compiled_start_plan = build_start_plan_graph().compile()
    return _compiled_start_plan


def get_next_step_agent():
    """Get or create the compiled next_step graph (singleton)."""
    global _compiled_next_step
    if _compiled_next_step is None:
        _compiled_next_step = build_next_step_graph().compile()
    return _compiled_next_step


def get_evaluate_agent():
    """Get or create the compiled evaluate graph (singleton)."""
    global _compiled_evaluate
    if _compiled_evaluate is None:
        _compiled_evaluate = build_evaluate_graph().compile()
    return _compiled_evaluate
