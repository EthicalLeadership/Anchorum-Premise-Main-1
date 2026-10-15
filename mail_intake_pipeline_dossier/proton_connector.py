"""
Dossier DOSSIER-PIPELINE ProtonMail Bridge IMAP Connector
Read-only ingestion. Never marks emails as read or deletes.
"""

import datetime
import imaplib
import ssl
from typing import List, Optional, Union


class ProtonMailConnector:
    """
    Connects to ProtonMail via Bridge IMAP (localhost:1143)
    or direct IMAP (imap.protonmail.ch:993) as fallback.
    """

    def __init__(
        self,
        email: str,
        password: str,
        host: str = "127.0.0.1",
        port: int = 1143,
        use_ssl: bool = False
    ):
        self.email = email
        self.password = password
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.mail: Optional[Union[imaplib.IMAP4_SSL, imaplib.IMAP4]] = None

    def connect(self) -> bool:
        """Establish IMAP connection. Returns True on success."""
        try:
            if self.use_ssl:
                context = ssl.create_default_context()
                self.mail = imaplib.IMAP4_SSL(self.host, self.port, ssl_context=context)
            else:
                self.mail = imaplib.IMAP4(self.host, self.port)
            self.mail.login(self.email, self.password)
            return True
        except Exception as exc:
            raise ConnectionError(
                f"ProtonMail IMAP connection failed ({self.host}:{self.port}): {exc}"
            ) from exc

    def fetch_unread(self, limit: int = 50, mailbox: str = "INBOX") -> List[bytes]:
        """
        Fetch raw bytes of unread messages.
        Uses UID commands to avoid wrong-message fetch after mailbox expunge (AV-05).
        Uses PEEK to avoid marking messages as read on server.
        """
        if not self.mail:
            raise RuntimeError("Not connected. Call connect() first.")

        self._select_mailbox(mailbox, readonly=True)
        _, data = self.mail.uid("search", None, "UNSEEN")
        uid_list = data[0].split()

        raw_messages: List[bytes] = []
        for uid in uid_list[-limit:]:
            _, msg_data = self.mail.uid("fetch", uid, "(BODY.PEEK[])")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    raw_messages.append(response_part[1])

        return raw_messages

    def fetch_all(self, limit: int = 500, mailbox: str = "INBOX") -> List[bytes]:
        """Fetch all messages regardless of read status."""
        if not self.mail:
            raise RuntimeError("Not connected. Call connect() first.")

        self._select_mailbox(mailbox, readonly=True)
        _, data = self.mail.uid("search", None, "ALL")
        uid_list = data[0].split()

        raw_messages: List[bytes] = []
        for uid in uid_list[-limit:]:
            _, msg_data = self.mail.uid("fetch", uid, "(BODY.PEEK[])")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    raw_messages.append(response_part[1])

        return raw_messages

    def disconnect(self):
        """Cleanly close IMAP session."""
        if self.mail:
            try:
                self.mail.close()
                self.mail.logout()
            except Exception:
                pass
            finally:
                self.mail = None

    def list_mailboxes(self) -> List[str]:
        """Return mailbox names visible to current account."""
        if not self.mail:
            raise RuntimeError("Not connected. Call connect() first.")

        status, data = self.mail.list()
        if status != "OK":
            raise RuntimeError("Unable to list mailboxes via IMAP LIST")

        names: List[str] = []
        for row in data:
            if not row:
                continue
            decoded = row.decode("utf-8", errors="replace") if isinstance(row, bytes) else str(row)
            # Typical format: (<flags>) "/" "Mailbox Name"
            if '"' in decoded:
                names.append(decoded.split('"')[-2])
            else:
                parts = decoded.split()
                if parts:
                    names.append(parts[-1])
        return names

    def _select_mailbox(self, mailbox: str, readonly: bool = True) -> None:
        """Select mailbox with graceful handling for case and spaces."""
        if not self.mail:
            raise RuntimeError("Not connected. Call connect() first.")

        try:
            status, _ = self.mail.select(mailbox, readonly=readonly)
            if status == "OK":
                return
        except Exception:
            pass

        # Retry with explicit quotes for mailbox names containing spaces.
        if " " in mailbox and not (mailbox.startswith('"') and mailbox.endswith('"')):
            quoted = f'"{mailbox}"'
            try:
                status, _ = self.mail.select(quoted, readonly=readonly)
                if status == "OK":
                    return
            except Exception:
                pass

        # Final fallback: resolve from LIST case-insensitively.
        try:
            available = self.list_mailboxes()
        except Exception:
            available = []

        target = mailbox.strip('"').lower()
        for candidate in available:
            if candidate.lower() == target:
                try:
                    status, _ = self.mail.select(candidate, readonly=readonly)
                    if status == "OK":
                        return
                except Exception:
                    pass

        raise RuntimeError(f"Unable to select mailbox '{mailbox}'.")

    def append_message(self, mailbox: str, raw_message: bytes, seen: bool = False) -> bool:
        """Append RFC822 message bytes into a mailbox (e.g., Drafts)."""
        if not self.mail:
            raise RuntimeError("Not connected. Call connect() first.")

        flags = "\\Seen" if seen else ""
        internaldate = imaplib.Time2Internaldate(datetime.datetime.now().timestamp())
        status, _ = self.mail.append(mailbox, flags, internaldate, raw_message)
        return status == "OK"
