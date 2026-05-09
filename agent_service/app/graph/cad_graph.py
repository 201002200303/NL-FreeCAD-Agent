"""
LangGraph graph builder for the CAD Agent workflow.

Stub — will be wired up with actual nodes in V0.4+.
"""

from langgraph.graph import StateGraph, END
from app.graph.state import AgentState
from app.graph.nodes import parse_input_node, plan_node, validate_plan_node


def build_cad_graph() -> StateGraph:
    """Build and return the CAD Agent workflow graph."""
    workflow = StateGraph(AgentState)

    workflow.add_node("parse_input", parse_input_node)
    workflow.add_node("plan", plan_node)
    workflow.add_node("validate_plan", validate_plan_node)

    workflow.set_entry_point("parse_input")
    workflow.add_edge("parse_input", "plan")
    workflow.add_edge("plan", "validate_plan")
    workflow.add_edge("validate_plan", END)

    return workflow


def create_cad_agent():
    """Create a compiled CAD Agent graph."""
    workflow = build_cad_graph()
    return workflow.compile()
