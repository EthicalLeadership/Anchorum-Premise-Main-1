from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class GapItem(BaseModel):
    id: str
    description: str
    status: str
    referenced_in_message_id: Optional[str] = None
    created_at: Optional[datetime] = None

class GapResponse(BaseModel):
    case_id: str
    total: int
    gaps: list[GapItem]
