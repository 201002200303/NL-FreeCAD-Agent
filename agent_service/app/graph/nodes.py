"""
LangGraph node functions.

Stub implementations — will be expanded in V0.4+.
"""

from app.graph.state import AgentState
from app.llm.planner import generate_plan


def parse_input_node(state: AgentState) -> AgentState:
    """Parse and normalize user input."""
    state["status"] = "parsing"
    return state


def plan_node(state: AgentState) -> AgentState:
    """Generate a modeling plan from user input."""
    result = generate_plan(state["user_input"], state.get("document_state"))
    state["plan_json"] = result
    state["status"] = result.get("status", "error")
    return state


def validate_plan_node(state: AgentState) -> AgentState:
    """Validate the generated plan against tool specs."""
    state["status"] = "validated" if state.get("plan_json") else "error"
    return state
