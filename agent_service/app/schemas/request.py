from pydantic import BaseModel, Field
from typing import Optional
from app.schemas.cad_state import DocumentState


class PlanRequest(BaseModel):
    user_input: str = Field(..., description="Natural language modeling request")
    document_state: Optional[DocumentState] = Field(
        default=None, description="Current FreeCAD document state"
    )
    conversation_id: Optional[str] = Field(
        default=None, description="Conversation ID for multi-turn"
    )
