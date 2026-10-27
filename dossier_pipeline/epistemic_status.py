"""
Epistemic Status Tracking

Tracks knowledge claims with their epistemic status:
- pending: Claim made but not yet verified
- verified: Claim supported by evidence
- disputed: Claim contradicted by evidence  
- resolved: Final determination reached

Each claim carries its epistemic_status and supporting rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class EpistemicStatus(str, Enum):
    """Epistemic status of a knowledge claim."""
    
    PENDING = "pending"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    RESOLVED = "resolved"
    WITHDRAWN = "withdrawn"


@dataclass
class EpistemicClaim:
    """A knowledge claim with epistemic status."""
    
    claim_id: str
    claim_text: str
    source: str  # Source of the claim (evidence, analysis, etc.)
    source_lines: List[int] = field(default_factory=list)
    
    status: EpistemicStatus = EpistemicStatus.PENDING
    rationale: Optional[str] = None
    
    # Evidence supporting this claim
    evidence_items: List[Dict[str, Any]] = field(default_factory=list)
    
    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status_changed_at: Optional[datetime] = None
    changed_by: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "claim_id": self.claim_id,
            "claim_text": self.claim_text,
            "source": self.source,
            "source_lines": self.source_lines,
            "status": self.status.value,
            "rationale": self.rationale,
            "evidence_items": self.evidence_items,
            "created_at": self.created_at.isoformat(),
            "status_changed_at": self.status_changed_at.isoformat() if self.status_changed_at else None,
            "changed_by": self.changed_by,
        }


@dataclass
class EpistemicRecord:
    """A record with epistemic status tracking."""
    
    record_id: str
    dossier_id: Optional[str] = None
    case_id: Optional[str] = None
    
    # Core epistemic fields
    execution_context_hash: str = ""
    epistemic_status: EpistemicStatus = EpistemicStatus.PENDING
    epistemic_rationale: Optional[str] = None
    
    # Claims associated with this record
    claims: List[EpistemicClaim] = field(default_factory=list)
    
    # Audit trail for status changes
    status_history: List[Dict[str, Any]] = field(default_factory=list)
    
    def add_claim(self, claim: EpistemicClaim) -> None:
        """Add a claim to this record."""
        self.claims.append(claim)
    
    def update_status(
        self,
        new_status: EpistemicStatus,
        rationale: Optional[str] = None,
        changed_by: Optional[str] = None,
    ) -> None:
        """Update epistemic status and record the change."""
        old_status = self.epistemic_status
        
        # Update status
        self.epistemic_status = new_status
        self.epistemic_rationale = rationale or f"Status changed from {old_status.value} to {new_status.value}"
        
        # Record the change in history
        self.status_history.append({
            "from": old_status.value,
            "to": new_status.value,
            "rationale": rationale,
            "changed_at": datetime.now(timezone.utc).isoformat(),
            "changed_by": changed_by or "system",
        })
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "record_id": self.record_id,
            "dossier_id": self.dossier_id,
            "case_id": self.case_id,
            "execution_context_hash": self.execution_context_hash,
            "epistemic_status": self.epistemic_status.value,
            "epistemic_rationale": self.epistemic_rationale,
            "claims": [claim.to_dict() for claim in self.claims],
            "status_history": self.status_history,
        }


def get_epistemic_record(record_id: str) -> Optional[EpistemicRecord]:
    """Get or create an epistemic record."""
    # In production, this would fetch from database
    return None  # Placeholder - implement with actual storage


def compute_epistemic_hash(record: EpistemicRecord) -> str:
    """Compute hash of epistemic state for integrity verification."""
    import hashlib
    
    # Build hash from status and claims (not history to avoid timestamp issues)
    hash_input = {
        "record_id": record.record_id,
        "epistemic_status": record.epistemic_status.value,
        "epistemic_rationale": record.epistemic_rationale or "",
        "claims": [claim.to_dict() for claim in record.claims],
    }
    
    sorted_input = json.dumps(hash_input, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(sorted_input.encode('utf-8')).hexdigest()


# Import json for the function above
import json
