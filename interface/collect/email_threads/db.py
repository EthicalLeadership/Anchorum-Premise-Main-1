import os
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

class EmailMessage(Base):
    __tablename__ = "email_messages"
    id = Column(String, primary_key=True)
    case_id = Column(String, nullable=False, index=True)
    document_id = Column(String, nullable=False, index=True)
    message_id_raw = Column(String, index=True)
    thread_id = Column(String, index=True)
    in_reply_to = Column(String)
    references = Column(Text)
    sent_at_raw = Column(String)
    sent_at = Column(DateTime)
    from_raw = Column(Text)
    to_raw = Column(Text)
    cc_raw = Column(Text)
    subject = Column(String)
    body_text = Column(Text)
    derivation = Column(String, nullable=False)
    content_hash = Column(String, nullable=True, index=True)
    trust_headers = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class ExpectedSource(Base):
    __tablename__ = "expected_sources"
    id = Column(String, primary_key=True)
    case_id = Column(String, nullable=False, index=True)
    description = Column(String)
    status = Column(String, default="REFERENCED")
    referenced_in_message_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

def get_engine(db_path="output/anchorum-local.db"):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

def init_email_schema(engine):
    Base.metadata.create_all(engine)

def get_session(engine):
    return sessionmaker(bind=engine)()


def get_db():
    engine = get_engine()
    db = get_session(engine)
    try:
        yield db
    finally:
        db.close()
