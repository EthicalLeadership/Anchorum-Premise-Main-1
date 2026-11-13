import json
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from interface.collect.email_threads.db import get_db, ExpectedSource, EmailMessage, FindingReview
from interface.findings import evaluate_findings
from .schemas import GapResponse, GapItem, ActorsResponse, CommEdge, ChronologyResponse, ChronologyEntry


def _safe_extract_addrs(raw: str) -> list[str]:
    try:
        rows = json.loads(raw or "[]")
        return [addr for row in rows for addr in row if addr]
    except (json.JSONDecodeError, TypeError):
        return []


board_router = APIRouter(prefix="/board", tags=["board"])

from dossier_pipeline.war_room.uncertainty import KnowledgeGap, GapSeverity

@board_router.get("/{case_id}/gaps", response_model=GapResponse)
def get_gaps(case_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(ExpectedSource)
        .filter(ExpectedSource.case_id == case_id)
        .order_by(ExpectedSource.created_at.desc())
        .all()
    )
    
    gaps = []
    for r in rows:
        # Bridge to the new engine's model
        kg = KnowledgeGap(
            id=r.id,
            case_id=r.case_id,
            description=r.description,
            severity=GapSeverity.MEDIUM # Default if not stored in DB
        )
        gaps.append(
            GapItem(
                id=kg.id,
                description=kg.description,
                status=r.status,
                severity=kg.severity.value,
                referenced_in_message_id=r.referenced_in_message_id,
                created_at=r.created_at,
            )
        )
        
    return GapResponse(
        case_id=case_id,
        total=len(gaps),
        gaps=gaps,
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

@board_router.get("/{case_id}/chronology", response_model=ChronologyResponse)
def get_chronology(case_id: str, db: Session = Depends(get_db)):
    # Query 2001 to detect truncation. Explicit NULL handling in SQL.
    rows = (
        db.query(EmailMessage)
        .filter(
            EmailMessage.case_id == case_id,
            EmailMessage.derivation.in_(["HEADER", "ATTACHMENT"]),
        )
        .order_by(EmailMessage.sent_at.is_(None), EmailMessage.sent_at.asc())
        .limit(2001)
        .all()
    )
    
    truncated = len(rows) > 2000
    if truncated:
        rows = rows[:2000]

    dated_entries = []
    undated_tray = []

    for row in rows:
        from_addrs = _safe_extract_addrs(row.from_raw)
        to_addrs = _safe_extract_addrs(row.to_raw)
        
        entry = ChronologyEntry(
            message_id=row.id,
            date=row.sent_at,
            date_raw=row.sent_at_raw,
            from_address=from_addrs[0] if from_addrs else None,
            to_address=to_addrs[0] if to_addrs else None,
            subject=row.subject,
            thread_id=row.thread_id
        )
        
        if row.sent_at:
            dated_entries.append(entry)
        else:
            undated_tray.append(entry)

    return ChronologyResponse(
        case_id=case_id,
        total_dated=len(dated_entries),
        total_undated=len(undated_tray),
        truncated=truncated,
        dated_entries=dated_entries,
        undated_tray=undated_tray
    )


class ReviewUpdate(BaseModel):
    status: str

@board_router.get("/{case_id}/findings")
def get_findings(case_id: str, db: Session = Depends(get_db)):
    rows = db.query(EmailMessage).filter(EmailMessage.case_id == case_id).all()
    messages = []
    for r in rows:
        messages.append({
            "id": r.id,
            "timestamp": r.sent_at.isoformat() + "Z" if r.sent_at else "1970-01-01T00:00:00Z",
            "from_actor": r.from_raw,
            "to_actor": r.to_raw,
            "channel": "email" if r.derivation in ("HEADER", "ATTACHMENT") else "document",
            "thread_id": r.thread_id or "none",
            "parent_id": None,
            "body": r.body_text or "",
            "needs_reply": False,
        })
    raw_findings = evaluate_findings(messages)
    reviews = db.query(FindingReview).filter(FindingReview.case_id == case_id).all()
    review_map = {r.id: r.status for r in reviews}
    for f in raw_findings:
        if f["id"] in review_map:
            f["status"] = review_map[f["id"]]
    return raw_findings

@board_router.post("/{case_id}/findings/{finding_id}")
def update_finding_status(
    case_id: str,
    finding_id: str,
    payload: ReviewUpdate,
    db: Session = Depends(get_db),
):
    if payload.status not in ("candidate", "confirmed", "dismissed"):
        raise HTTPException(status_code=400, detail="Invalid status")

    review = db.query(FindingReview).filter(
        FindingReview.id == finding_id,
        FindingReview.case_id == case_id,
    ).first()

    if review:
        review.status = payload.status
    else:
        review = FindingReview(
            id=finding_id,
            case_id=case_id,
            status=payload.status,
            reviewed_by="system",
        )
        db.add(review)

    db.commit()
    return {"id": finding_id, "status": payload.status}
