"""
Dossier DOSSIER-PIPELINE Email Intake & Deduplication
MIME parsing, attachment extraction, cryptographic fingerprinting.
"""

import base64
import datetime
import email
import hashlib
import io
import sqlite3
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional

from .contracts import EmailEnvelope


class EmailSeenSet:
    """Persistent deduplication of message IDs using SQLite."""

    PENDING_CLAIM_TTL_SECONDS = 900

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_messages (
                message_id TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'processed',
                last_updated TEXT NOT NULL DEFAULT ''
            )
        """)
        columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(seen_messages)")
        }
        if "status" not in columns:
            self.conn.execute(
                "ALTER TABLE seen_messages "
                "ADD COLUMN status TEXT NOT NULL DEFAULT 'processed'"
            )
        if "last_updated" not in columns:
            self.conn.execute(
                "ALTER TABLE seen_messages "
                "ADD COLUMN last_updated TEXT NOT NULL DEFAULT ''"
            )
            self.conn.execute(
                "UPDATE seen_messages SET last_updated = first_seen "
                "WHERE last_updated = ''"
            )
        self.conn.commit()

    def _normalize_message_id(self, message_id: str) -> str:
        """CF-02: Canonical form for dedup lookup (lowercase, no angle brackets, stripped)."""
        return message_id.strip().strip("<>").lower().strip()

    def has_seen(self, message_id: str) -> bool:
        key = self._normalize_message_id(message_id)
        cur = self.conn.execute(
            "SELECT 1 FROM seen_messages WHERE message_id = ?", (key,)
        )
        return cur.fetchone() is not None

    def get_sha256(self, message_id: str) -> Optional[str]:
        """Return stored sha256 for a message_id, or None if not seen."""
        key = self._normalize_message_id(message_id)
        cur = self.conn.execute(
            "SELECT sha256 FROM seen_messages WHERE message_id = ?", (key,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    def has_sha256(self, sha256: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM seen_messages WHERE sha256 = ? LIMIT 1",
            (sha256,),
        )
        return cur.fetchone() is not None

    def _claim_is_stale(self, timestamp: str) -> bool:
        if not timestamp:
            return True
        try:
            claimed_at = datetime.datetime.fromisoformat(timestamp)
        except ValueError:
            return True
        age = datetime.datetime.now() - claimed_at
        return age.total_seconds() >= self.PENDING_CLAIM_TTL_SECONDS

    def claim_message(self, message_id: str, sha256: str) -> str:
        """
        Atomically reserve a message for processing.

        Returns one of:
          - "claimed": caller owns processing
          - "seen": already fully processed
          - "in_progress": another worker already claimed it
          - "conflict": same message_id was seen with different content
        """
        key = self._normalize_message_id(message_id)
        now = datetime.datetime.now().isoformat()

        try:
            self.conn.execute("BEGIN IMMEDIATE")
            cur = self.conn.execute(
                "SELECT sha256, status, last_updated FROM seen_messages WHERE message_id = ?",
                (key,),
            )
            row = cur.fetchone()

            if row is None:
                self.conn.execute(
                    """
                    INSERT INTO seen_messages
                    (message_id, sha256, first_seen, status, last_updated)
                    VALUES (?, ?, ?, 'pending', ?)
                    """,
                    (key, sha256, now, now),
                )
                self.conn.commit()
                return "claimed"

            stored_sha, status, last_updated = row
            if stored_sha != sha256:
                self.conn.commit()
                return "conflict"

            if status == "pending" and self._claim_is_stale(last_updated):
                self.conn.execute(
                    """
                    UPDATE seen_messages
                    SET sha256 = ?, status = 'pending', last_updated = ?
                    WHERE message_id = ?
                    """,
                    (sha256, now, key),
                )
                self.conn.commit()
                return "claimed"

            self.conn.commit()
            return "seen" if status == "processed" else "in_progress"
        except Exception:
            self.conn.rollback()
            raise

    def mark_seen(self, message_id: str, sha256: str):
        key = self._normalize_message_id(message_id)
        now = datetime.datetime.now().isoformat()
        self.conn.execute(
            """
            INSERT INTO seen_messages
            (message_id, sha256, first_seen, status, last_updated)
            VALUES (?, ?, ?, 'processed', ?)
            ON CONFLICT(message_id) DO UPDATE SET
                sha256 = excluded.sha256,
                status = 'processed',
                last_updated = excluded.last_updated
            """,
            (key, sha256, now, now),
        )
        self.conn.commit()

    def count(self) -> int:
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM seen_messages WHERE status = 'processed'"
        )
        return cur.fetchone()[0]

    def get_all(self) -> List[dict]:
        """
        Return the current seen-message table as a stable read-only snapshot.

        This is the bridge needed for projection inversion: callers can compare
        the legacy SQLite state against a derived view without mutating it.
        """
        cur = self.conn.execute(
            """
            SELECT message_id, sha256, first_seen, status, last_updated
            FROM seen_messages
            ORDER BY first_seen ASC
            """
        )
        cols = [desc[0] for desc in cur.description]
        rows = []
        for row in cur.fetchall():
            rows.append(dict(zip(cols, row)))
        return rows

    def close(self):
        """Release the underlying SQLite connection."""
        self.conn.close()


class EmailIntake:
    """Parse raw MIME bytes into governed EmailEnvelope objects."""

    CONFLICT_ID_HEX_LENGTH = 64
    ARCHIVE_MAX_BYTES = 25 * 1024 * 1024
    ARCHIVE_MAX_ENTRIES = 512
    ARCHIVE_MAX_PATH_DEPTH = 6
    ARCHIVE_MAX_COMPRESSION_RATIO = 100.0

    def __init__(self, seen_set: EmailSeenSet):
        self.seen_set = seen_set

    def _build_message_key(self, message_id: str, date: str, sender: str) -> str:
        return hashlib.sha256(
            f"{message_id}:{date}:{sender}".encode()
        ).hexdigest()[:32]

    def _decode_with_fallbacks(self, payload: bytes, declared_charset: Optional[str]) -> str:
        candidates: List[str] = []

        if declared_charset:
            candidates.append(declared_charset)

        # Honor common BOM signatures before generic fallbacks.
        if payload.startswith(b"\xff\xfe"):
            candidates.append("utf-16-le")
        elif payload.startswith(b"\xfe\xff"):
            candidates.append("utf-16-be")
        elif payload.startswith(b"\xef\xbb\xbf"):
            candidates.append("utf-8-sig")

        candidates.extend([
            "utf-8",
            "utf-16",
            "ascii",
            "latin-1",
        ])

        tried = set()
        for charset in candidates:
            normalized = (charset or "").strip().lower()
            if not normalized or normalized in tried:
                continue
            tried.add(normalized)
            try:
                return payload.decode(normalized)
            except (LookupError, UnicodeDecodeError):
                if normalized.startswith("utf-16"):
                    trimmed = payload.rstrip(b"\r\n")
                    if trimmed and len(trimmed) % 2 == 0:
                        try:
                            return trimmed.decode(normalized)
                        except (LookupError, UnicodeDecodeError):
                            pass
                continue

        # Last-resort path keeps processing alive and makes data loss explicit.
        return payload.decode("utf-8", errors="replace")

    def _decode_part(self, part) -> str:
        payload = part.get_payload(decode=True)
        if not payload:
            return ""

        return self._decode_with_fallbacks(payload, part.get_content_charset())

    def _html_to_text(self, html: str) -> str:
        class _HTMLTextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.chunks: List[str] = []

            def handle_data(self, data: str):
                stripped = data.strip()
                if stripped:
                    self.chunks.append(stripped)

        parser = _HTMLTextExtractor()
        parser.feed(html)
        return " ".join(parser.chunks)

    def _looks_like_archive(self, filename: str, content_type: str) -> bool:
        lowered_name = (filename or "").lower()
        lowered_type = (content_type or "").lower()
        archive_suffixes = (".zip", ".tar", ".tar.gz", ".tgz", ".gz", ".bz2", ".7z", ".rar")
        if lowered_name.endswith(archive_suffixes):
            return True
        return "zip" in lowered_type or "archive" in lowered_type

    def _member_path_depth(self, member_name: str) -> int:
        clean = member_name.strip("/")
        if not clean:
            return 0
        return len([part for part in clean.split("/") if part])

    def _inspect_archive(self, data: bytes, filename: str, content_type: str) -> dict:
        report = {
            "archive": True,
            "archive_type": "zip" if (filename or "").lower().endswith(".zip") or "zip" in (content_type or "").lower() else "unknown",
            "archive_status": "ok",
            "archive_size_bytes": len(data),
        }

        if len(data) > self.ARCHIVE_MAX_BYTES:
            report.update(
                {
                    "archive_status": "skipped_oversize",
                    "archive_error": f"archive exceeds {self.ARCHIVE_MAX_BYTES} bytes",
                }
            )
            return report

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                infos = archive.infolist()
        except (zipfile.BadZipFile, OSError):
            report.update(
                {
                    "archive_status": "corrupt_archive",
                    "archive_error": "unable to parse archive container",
                }
            )
            return report

        all_entry_count = len(infos)
        inspected_infos = infos[: self.ARCHIVE_MAX_ENTRIES]
        uncompressed_total = sum(info.file_size for info in infos)
        max_path_depth = max((self._member_path_depth(info.filename) for info in inspected_infos), default=0)
        nested_archives = [
            info.filename
            for info in inspected_infos
            if self._looks_like_archive(info.filename, "")
        ]

        compression_ratio = (
            float(uncompressed_total) / float(len(data)) if len(data) > 0 else 0.0
        )

        report.update(
            {
                "archive_entry_count": all_entry_count,
                "archive_entries_inspected": len(inspected_infos),
                "archive_entries_truncated": all_entry_count > self.ARCHIVE_MAX_ENTRIES,
                "archive_uncompressed_total": uncompressed_total,
                "archive_compression_ratio": round(compression_ratio, 2),
                "archive_max_path_depth": max_path_depth,
                "archive_nested_entry_count": len(nested_archives),
            }
        )

        if all_entry_count > self.ARCHIVE_MAX_ENTRIES:
            report["archive_status"] = "too_many_entries"
        elif max_path_depth > self.ARCHIVE_MAX_PATH_DEPTH:
            report["archive_status"] = "path_depth_exceeded"
        elif compression_ratio > self.ARCHIVE_MAX_COMPRESSION_RATIO:
            report["archive_status"] = "suspicious_compression_ratio"
        elif nested_archives:
            report["archive_status"] = "nested_archive_detected"

        return report

    def parse_email_bytes(self, raw_bytes: bytes) -> EmailEnvelope:
        msg = email.message_from_bytes(raw_bytes)

        message_id = msg.get("Message-ID", "").strip()
        subject = msg.get("Subject", "")
        sender = msg.get("From", "")
        recipient = msg.get("To", "")
        date = msg.get("Date", "")

        received_headers = [h.strip() for h in (msg.get_all("Received", []) or []) if h and h.strip()]
        received_count = len(received_headers)

        received_first_ts = ""
        received_last_ts = ""
        if received_headers:
            # Best-effort timestamp extraction: use the portion after the last ';'
            parsed_ts: List[str] = []
            for h in received_headers:
                date_part = h.split(";")[-1].strip() if ";" in h else h.strip()
                try:
                    dt = email.utils.parsedate_to_datetime(date_part)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=datetime.timezone.utc)
                    parsed_ts.append(dt.isoformat())
                except Exception:
                    continue
            if parsed_ts:
                received_first_ts = parsed_ts[0]
                received_last_ts = parsed_ts[-1]

        # Base64-encoded fingerprint of normalized Received header list (MD-safe).
        received_chain_fingerprint_b64 = ""
        if received_headers:
            joined = "\n".join(received_headers)
            digest = hashlib.sha256(joined.encode("utf-8")).digest()
            received_chain_fingerprint_b64 = base64.b64encode(digest).decode("ascii")

        plain_parts: List[str] = []
        html_parts: List[str] = []
        attachments: List[dict] = []

        if msg.is_multipart():
            for part in msg.walk():
                if part.is_multipart():
                    continue
                content_type = part.get_content_type()
                filename = part.get_filename()
                if filename:
                    att_data = part.get_payload(decode=True) or b""
                    attachment_record = {
                        "filename": filename,
                        "content_type": content_type,
                        "size": len(att_data),
                        "sha256": hashlib.sha256(att_data).hexdigest()
                    }
                    if self._looks_like_archive(filename, content_type):
                        attachment_record.update(
                            self._inspect_archive(att_data, filename, content_type)
                        )
                    attachments.append(attachment_record)
                    continue

                if content_type == "text/plain":
                    text = self._decode_part(part)
                    if text:
                        plain_parts.append(text)
                elif content_type == "text/html":
                    text = self._html_to_text(self._decode_part(part))
                    if text:
                        html_parts.append(text)
        else:
            content_type = msg.get_content_type()
            text = self._decode_part(msg)
            if text:
                if content_type == "text/html":
                    html_parts.append(self._html_to_text(text))
                else:
                    plain_parts.append(text)

        body_text = "\n".join(part for part in plain_parts if part).strip()
        if not body_text:
            body_text = "\n".join(part for part in html_parts if part).strip()

        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()

        # If Message-ID is absent, generate a synthetic one from content fingerprint.
        # This prevents all headerless emails from colliding on the empty-string key
        # and being silently dropped after the first one.
        if not message_id:
            message_id = (
                f"<synthetic-"
                f"{hashlib.sha256(f'{sender}:{date}:{raw_sha256}'.encode()).hexdigest()[:32]}"
                f"@local>"
            )

        message_key = self._build_message_key(message_id, date, sender)

        return EmailEnvelope(
            message_id=message_id,
            subject=subject,
            sender=sender,
            recipient=recipient,
            date=date,
            body_text=body_text,
            attachments=attachments,

            received_count=received_count,
            received_first_ts=received_first_ts,
            received_last_ts=received_last_ts,
            received_chain_fingerprint_b64=received_chain_fingerprint_b64,

            raw_sha256=raw_sha256,
            message_key=message_key,
            original_message_id=message_id,
            ingest_timestamp=datetime.datetime.now().isoformat(),

            # For a real message the artifact IS the message: the bytes ingested
            # and the bytes submitted are the same bytes, so the two hashes are
            # equal and nothing about the envelope was invented. `transport`
            # stays "email" and `synthesised_fields` stays empty. (A headerless
            # message still gets a content-derived Message-ID above, which is a
            # derived identity rather than an invented value.)
            source_sha256=raw_sha256,
            source_bytes=len(raw_bytes),
            source_media_type="message/rfc822",
            transport="email",
            synthesised_fields=(),
        )

    def normalize(self, envelope: EmailEnvelope) -> Optional[EmailEnvelope]:
        """
        Deduplicate without mutating canonical seen-state beyond a read-only check.
        Returns the envelope when the message has not been seen; returns None for
        duplicates or in-progress claims.

        If the same Message-ID arrives with different content, preserve the new
        message as a conflict variant with a deterministic synthetic identity so
        the caller can process and record it separately.
        """
        if self.seen_set.has_seen(envelope.message_id):
            stored_sha = self.seen_set.get_sha256(envelope.message_id)
            if stored_sha == envelope.raw_sha256:
                return None

            conflict_message_id = (
                f"conflict-{envelope.raw_sha256[:self.CONFLICT_ID_HEX_LENGTH]}@local"
            )
            if self.seen_set.has_sha256(envelope.raw_sha256):
                return None

            envelope.subject = f"[CONFLICT-DUPLICATE] {envelope.subject}"
            envelope.message_id = conflict_message_id
            envelope.message_key = self._build_message_key(
                envelope.message_id,
                envelope.date,
                envelope.sender,
            )
            return envelope

        claim_status = self.seen_set.claim_message(
            envelope.message_id,
            envelope.raw_sha256,
        )
        if claim_status != "claimed":
            return None

        return envelope
