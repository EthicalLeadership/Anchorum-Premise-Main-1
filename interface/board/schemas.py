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

class CommEdge(BaseModel):
    from_address: str
    to_address: str
    count: int
    first_contact: Optional[datetime] = None
    last_contact: Optional[datetime] = None

class ActorsResponse(BaseModel):
    case_id: str
    total_messages: int
    unique_actors: int
    edges: list[CommEdge]
