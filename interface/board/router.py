import json
from collections import defaultdict
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from interface.collect.email_threads.db import get_db, ExpectedSource, EmailMessage
from .schemas import GapResponse, GapItem, ActorsResponse, CommEdge

board_router = APIRouter(prefix="/board", tags=["board"])

@board_router.get("/{case_id}/gaps", response_model=GapResponse)
def get_gaps(case_id: str, db: Session = Depends(get_db)):
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

@board_router.get("/{case_id}/actors", response_model=ActorsResponse)
def get_actors(case_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(EmailMessage)
        .filter(
            EmailMessage.case_id == case_id,
            EmailMessage.derivation.in_(["HEADER", "ATTACHMENT"]),
        )
        .all()
    )

    edges = defaultdict(lambda: {"count": 0, "first": None, "last": None})
    actors = set()

    for row in rows:
        try:
            froms = json.loads(row.from_raw or "[]")
            tos = json.loads(row.to_raw or "[]")
        except (json.JSONDecodeError, TypeError):
            continue

        from_addrs = [a for _, a in froms if a]
        to_addrs = [a for _, a in tos if a]
        actors.update(from_addrs)
        actors.update(to_addrs)

        for fa in from_addrs:
            for ta in to_addrs:
                if fa == ta:
                    continue
                edge = edges[(fa, ta)]
                edge["count"] += 1
                ts = row.sent_at
                if ts:
                    if edge["first"] is None or ts < edge["first"]:
                        edge["first"] = ts
                    if edge["last"] is None or ts > edge["last"]:
                        edge["last"] = ts

    sorted_edges = sorted(edges.items(), key=lambda kv: kv[1]["count"], reverse=True)
    return ActorsResponse(
        case_id=case_id,
        total_messages=len(rows),
        unique_actors=len(actors),
        edges=[
            CommEdge(
                from_address=fa,
                to_address=ta,
                count=data["count"],
                first_contact=data["first"],
                last_contact=data["last"],
            )
            for (fa, ta), data in sorted_edges
        ],
    )
