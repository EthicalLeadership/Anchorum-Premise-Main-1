"""
Dossier DOSSIER-PIPELINE Lightweight Structured Logging

Provides a minimal JSON line logger for operational visibility without adding
third-party dependencies. The logger is intentionally simple and local-first so
it can be used by CLI commands and pipeline stages without changing the audit
model.
"""

from __future__ import annotations

import datetime
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, TextIO


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@dataclass
class StructuredLogger:
    stream: TextIO = field(default=sys.stdout)

    def emit(self, event: str, **fields: Any) -> None:
        payload: Dict[str, Any] = {
            "timestamp_utc": _utc_now(),
            "event": event,
            **fields,
        }
        self.stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        self.stream.flush()
