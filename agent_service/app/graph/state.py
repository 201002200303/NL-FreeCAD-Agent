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
