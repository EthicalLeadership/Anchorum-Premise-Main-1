"""Document handler: text or file → full dossier pipeline → JSON-safe result."""
from __future__ import annotations

import os as _os
import uuid

# Interface runs on 127.0.0.1 only; the dev signing key is the correct key here.
_os.environ.setdefault("ANCHORUM_ENV", "local")

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import default as default_policy
from enum import Enum
from pathlib import Path
from typing import Any

from dossier_pipeline.main import load_config
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
    cfg.setdefault("output_dir", "./output")
    cfg.setdefault("email", "interface@localhost")
    return cfg


def _wrap_text_as_eml(text: str, subject: str, sender: str, recipient: str) -> bytes:
    msg = EmailMessage(policy=default_policy)
    msg["Message-ID"] = f"<{uuid.uuid4().hex}@interface.local>"
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg.set_content(text)
    return msg.as_bytes()


def _build_pipeline() -> DossierPipeline:
    cfg = _config()
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
):
    """Wrap plain text in a synthetic message and run it through the pipeline."""
    return pipeline.process_email(
        _wrap_text_as_eml(body, subject, sender, cfg["email"])
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
                result = _submit_text(pipeline, body, cfg, subject, sender)
            else:
                # No filename, or a MIME message: the bytes are the message.
                result = pipeline.process_email(raw_bytes)
        elif file_path is not None:
            p = Path(file_path)
            if p.suffix.lower() == ".eml":
                result = pipeline.process_file(str(p))
            else:
                body = submission.extract_text_from_file(p)
                result = _submit_text(pipeline, body, cfg, subject, sender)
        else:
            result = _submit_text(pipeline, text or "", cfg, subject, sender)

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
