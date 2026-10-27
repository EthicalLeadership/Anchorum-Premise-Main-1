"""
Deterministic Execution Context Hashing

Captures all inputs that affect output determinism:
- Config hashes (lexicon, prompts, engine settings)
- Environment variables (model names, API endpoints)
- Timestamps (for audit trail, not for hash computation)
- Input ordering (message IDs, file paths)

The execution_context_hash is computed once per dossier and cached.
Re-running with same inputs produces identical hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class ExecutionContext:
    """Captures all inputs affecting deterministic execution."""
    
    # Core configuration hashes
    lexicon_hash: str = ""
    config_hash: str = ""
    prompts_hash: str = ""
    
    # Environment snapshot (without secrets)
    model_name: str = ""
    ollama_url: str = ""
    classifier_model: str = ""
    
    # System state
    python_version: str = ""
    platform: str = ""
    
    # Dossier-specific inputs
    dossier_id: Optional[str] = None
    case_id: Optional[str] = None
    
    # Timestamp for audit trail (NOT included in hash)
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Raw context data for debugging
    raw_context: Dict[str, Any] = field(default_factory=dict)
    
    def compute_hash(self) -> str:
        """Compute deterministic hash of execution context."""
        # Build hash from all fields EXCEPT captured_at and raw_context
        hash_input = {
            "lexicon_hash": self.lexicon_hash,
            "config_hash": self.config_hash,
            "prompts_hash": self.prompts_hash,
            "model_name": self.model_name,
            "ollama_url": self.ollama_url,
            "classifier_model": self.classifier_model,
            "python_version": self.python_version,
            "platform": self.platform,
            "dossier_id": self.dossier_id or "",
            "case_id": self.case_id or "",
        }
        
        # Sort keys to ensure deterministic ordering
        sorted_input = json.dumps(hash_input, sort_keys=True, separators=(',', ':'))
        
        # Compute SHA-256 hash
        return hashlib.sha256(sorted_input.encode('utf-8')).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "lexicon_hash": self.lexicon_hash,
            "config_hash": self.config_hash,
            "prompts_hash": self.prompts_hash,
            "model_name": self.model_name,
            "ollama_url": self.ollama_url,
            "classifier_model": self.classifier_model,
            "python_version": self.python_version,
            "platform": self.platform,
            "dossier_id": self.dossier_id,
            "case_id": self.case_id,
            "captured_at": self.captured_at.isoformat(),
        }


def get_execution_context(dossier_id: Optional[str] = None, case_id: Optional[str] = None) -> ExecutionContext:
    """Get or create execution context for current execution."""
    
    # Capture environment (excluding secrets)
    import os
    
    return ExecutionContext(
        lexicon_hash=os.environ.get("LEXICON_HASH", ""),
        config_hash=os.environ.get("CONFIG_HASH", ""),
        prompts_hash=os.environ.get("PROMPTS_HASH", ""),
        model_name=os.environ.get("CLF_MODEL", "llama3.1:8b"),
        ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate"),
        classifier_model=os.environ.get("CLF_MODEL", "llama3.1:8b"),
        python_version=f"{__import__('sys').version_info.major}.{__import__('sys').version_info.minor}",
        platform=f"{__import__('platform').system()}-{__import__('platform').machine()}",
        dossier_id=dossier_id,
        case_id=case_id,
    )


def compute_execution_context_hash(dossier_id: Optional[str] = None, case_id: Optional[str] = None) -> str:
    """Compute and return execution context hash."""
    ctx = get_execution_context(dossier_id, case_id)
    return ctx.compute_hash()
