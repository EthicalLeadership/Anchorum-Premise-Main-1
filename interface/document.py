"""Document handler: text or file → full dossier pipeline → JSON-safe result."""
from __future__ import annotations

import hashlib
import os as _os

# Interface runs on 127.0.0.1 only; the dev signing key is the correct key here.
_os.environ.setdefault("ANCHORUM_ENV", "local")

from dataclasses import asdict, is_dataclass
from email.message import EmailMessage
from email.policy import default as default_policy
from enum import Enum
from pathlib import Path
from typing import Any

from dossier_pipeline.main import load_config
from dossier_pipeline.evidence import EvidenceStore
from dossier_pipeline.pipeline import DossierPipeline, load_default_spec
from interface import submission


def _json_safe(v: Any) -> Any:
    if isinstance(v, Enum):
        return v.value
    if is_dataclass(v) and not isinstance(v, type):
        return {k: _json_safe(x) for k, x in asdict(v).items()}
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set, frozenset)):
        return [_json_safe(x) for x in v]
    if isinstance(v, bytes):
        return v.hex()
    return v


def _config() -> dict:
    cfg = load_config()
    cfg.setdefault("dossier_id", "INTERFACE")
    cfg.setdefault(
        "output_dir",
        _os.environ.get("ANCHORUM_OUTPUT_DIR") or "./output",
    )
    cfg.setdefault("email", "interface@localhost")
    return cfg


def _pipeline_config() -> dict:
    cfg = _config()
    cfg["output_dir"] = str(Path(cfg["output_dir"]).expanduser().resolve())
    return cfg


def resolve_evidence_db_path() -> Path:
    """Resolve the evidence database used by this module's pipeline factory."""
    cfg = _pipeline_config()
    return Path(cfg["output_dir"]) / f"{cfg['dossier_id']}_evidence.db"


def open_evidence_store() -> EvidenceStore:
    """Open a fresh store for the configured pipeline database; caller closes it."""
    db_path = resolve_evidence_db_path()
    if not db_path.is_file():
        raise FileNotFoundError(f"Evidence database does not exist: {db_path}")
    return EvidenceStore(str(db_path))


#: Transport name for a submission that arrived as a document rather than mail.
TRANSPORT_DOCUMENT = "document"

#: Envelope fields this bridge invents. Named so the signed record can tell
#: them from values that were observed.
SYNTHESISED_DOCUMENT_FIELDS = ("message_id", "subject", "sender", "recipient", "date")

#: Fixed timestamp for synthetic wrappers. A wall clock here makes the recorded
#: identity a function of when ingestion ran rather than of what was ingested,
#: which is exactly what made the same PDF hash differently on every run.
SYNTHETIC_WRAPPER_DATE = "Thu, 01 Jan 1970 00:00:00 +0000"


def _wrap_text_as_eml(
    text: str,
    subject: str,
    sender: str,
    recipient: str,
    source_sha256: str,
) -> bytes:
    """Build the synthetic message a document submission travels as.

    Deterministic in the artifact and nothing else. The Message-ID is derived
    from the artifact hash and the Date is a constant, so the same bytes ingest
    to the same identity every time and a genuine resubmission is recognised as
    a duplicate rather than accepted as new.

    The filename is deliberately absent from this wrapper. Dedup keys on the
    normalized Message-ID, so a name-sensitive wrapper would make the same bytes
    under a new name a brand-new submission forever. The name travels as
    `source_filename` metadata instead.
    """
    msg = EmailMessage(policy=default_policy)
    stable = hashlib.sha256(source_sha256.encode("utf-8")).hexdigest()[:32]
    msg["Message-ID"] = f"<{stable}@document.local>"
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg["Date"] = SYNTHETIC_WRAPPER_DATE
    msg.set_content(text)
    return msg.as_bytes()


def _document_source(
    source_sha256: str,
    byte_size: int,
    filename: str,
    media_type: str,
) -> dict:
    """The artifact identity a document submission carries into the pipeline."""
    return {
        "source_sha256": source_sha256,
        "source_bytes": byte_size,
        "source_filename": filename,
        "source_media_type": media_type,
        "transport": TRANSPORT_DOCUMENT,
        "synthesised_fields": SYNTHESISED_DOCUMENT_FIELDS,
    }


def _build_pipeline() -> DossierPipeline:
    cfg = _pipeline_config()
    return DossierPipeline(
        dossier_id=cfg["dossier_id"],
        output_dir=cfg["output_dir"],
        state_machine_spec=load_default_spec(),
    )


def _submit_text(
    pipeline: DossierPipeline,
    body: str,
    cfg: dict,
    subject: str,
    sender: str,
    source: dict,
):
    """Wrap plain text in a synthetic message and run it through the pipeline."""
    return pipeline.process_email(
        _wrap_text_as_eml(
            body,
            subject,
            sender,
            cfg["email"],
            source["source_sha256"],
        ),
        source=source,
    )


def process(
    *,
    text: str | None = None,
    raw_bytes: bytes | None = None,
    file_path: str | None = None,
    filename: str | None = None,
    subject: str = "(interface submission)",
    sender: str = "interface@localhost",
) -> dict:
    """Run one submission through the dossier pipeline.

    Dispatch is by artifact type, not by "is it an .eml" alone. Everything that
    used to be decoded as UTF-8 with ``errors="replace"`` now goes through
    ``interface.submission``, which reads PDFs properly and refuses artifact
    types it cannot honestly read. Decoding a PDF as text does not fail, it
    succeeds wrongly, and the pipeline would then commit and sign a control
    record about content nobody had read.
    """
    provided = [x for x in (text, raw_bytes, file_path) if x is not None]
    if len(provided) != 1:
        raise ValueError("provide exactly one of text, raw_bytes, file_path")

    cfg = _config()
    with _build_pipeline() as pipeline:
        if raw_bytes is not None:
            name = filename or ""
            if name and not submission.is_eml(raw_bytes, name):
                body = submission.extract_text(raw_bytes, name)
                source = _document_source(
                    hashlib.sha256(raw_bytes).hexdigest(),
                    len(raw_bytes),
                    name,
                    "application/octet-stream",
                )
                result = _submit_text(pipeline, body, cfg, subject, sender, source)
            else:
                # No filename, or a MIME message: the bytes are the message, so
                # the parser's own artifact identity already applies.
                result = pipeline.process_email(raw_bytes)
        elif file_path is not None:
            p = Path(file_path)
            if p.suffix.lower() == ".eml":
                result = pipeline.process_file(str(p))
            else:
                # Read once, so the hash and the text describe the same bytes.
                document_bytes = p.read_bytes()
                body = submission.extract_text(document_bytes, p.name)
                source = _document_source(
                    hashlib.sha256(document_bytes).hexdigest(),
                    len(document_bytes),
                    p.name,
                    "application/octet-stream",
                )
                result = _submit_text(pipeline, body, cfg, subject, sender, source)
        else:
            # A bare string has no artifact of its own. The record says so: the
            # hash is of the text that was submitted, and the name is empty.
            payload_text = text or ""
            encoded = payload_text.encode("utf-8")
            source = _document_source(
                hashlib.sha256(encoded).hexdigest(),
                len(encoded),
                "",
                "text/plain",
            )
            result = _submit_text(pipeline, payload_text, cfg, subject, sender, source)

        return {
            "status": result.status.value,
            "message_key": result.message_key,
            "message_id": result.message_id,
            "actor": result.actor,
            "route": result.route,
            "reason": result.reason,
            "record_hash": result.record_hash,
            "previous_hash": result.previous_hash,
            "raw_sha256": result.raw_sha256,
            "retryable": result.retryable,
            "data": _json_safe(result.data),
        }
