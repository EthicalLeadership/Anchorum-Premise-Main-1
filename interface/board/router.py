from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from interface.collect.email_threads.db import get_db, ExpectedSource
from .schemas import GapResponse, GapItem

board_router = APIRouter(prefix="/board", tags=["board"])

@board_router.get("/{case_id}/gaps", response_model=GapResponse)
def get_gaps(case_id: str, db: Session = Depends(get_db)):
    # TODO: add case-level authorization here (JWT / membership check)
    gaps = (
        db.query(ExpectedSource)
        .filter(ExpectedSource.case_id == case_id)
        .order_by(ExpectedSource.created_at.desc())
        .all()
    )
    return GapResponse(
        case_id=case_id,
        total=len(gaps),
        gaps=[
            GapItem(
                id=g.id,
                description=g.description,
                status=g.status,
                referenced_in_message_id=g.referenced_in_message_id,
                created_at=g.created_at,
            )
            for g in gaps
        ],
    )
