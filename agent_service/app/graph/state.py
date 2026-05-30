from typing import Optional, TypedDict
from app.schemas.cad_state import DocumentState


class AgentState(TypedDict):
    """State passed between LangGraph nodes."""
    user_input: str
    document_state: Optional[DocumentState]
    plan_json: Optional[dict]
    status: str
    error_message: Optional[str]
    conversation_id: Optional[str]
    retry_count: int
    validation_errors: list[str]

    # V0.7: High-level plan fields
    high_level_plan: Optional[dict]
    phases: Optional[list[dict]]
    current_phase_id: Optional[str]

    # V0.7: Next step fields
    session_id: Optional[str]
    execution_history: Optional[dict]
    name_map: Optional[dict[str, str]]
    next_step_result: Optional[dict]

    # V0.7: Evaluate step fields
    last_tool_call: Optional[dict]
    execution_result: Optional[dict]
    evaluate_result: Optional[dict]
