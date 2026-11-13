from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class GapItem(BaseModel):
    id: str
    description: str
    status: str
    severity: str = "medium"
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

class ChronologyEntry(BaseModel):
    message_id: str
    date: Optional[datetime] = None
    date_raw: Optional[str] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    subject: Optional[str] = None
    thread_id: Optional[str] = None

class ChronologyResponse(BaseModel):
    case_id: str
    total_dated: int
    total_undated: int
    truncated: bool = False
    dated_entries: list[ChronologyEntry]
    undated_tray: list[ChronologyEntry]
