from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
import uuid

from .ingest import ingest
from .db import get_session, get_engine
from .abort import ParsingAbort

router = APIRouter(prefix="/intake", tags=["email_intake"])

def get_db():
    engine = get_engine()
    db = get_session(engine)
    try:
        yield db
    finally:
        db.close()

@router.post("/{case_id}/email")
async def upload_email(
    case_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    if not file.filename.endswith((".eml", ".msg")):
        raise HTTPException(status_code=400, detail="Only .eml or .msg files are supported")
    
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="File is empty")
        
    try:
        document_id = str(uuid.uuid4())
        rows = ingest(case_id, document_id, raw_bytes, db)
        return {
            "status": "ok", 
            "document_id": document_id,
            "messages_ingested": len(rows)
        }
    except ParsingAbort as e:
        # Catch our specific parser errors and return a 422
        raise HTTPException(status_code=422, detail=f"Parsing aborted: {e.reason}")
    except Exception as e:
        # Log the actual error internally, don't leak stack traces to the client
        raise HTTPException(status_code=500, detail="Internal server error during ingestion")
