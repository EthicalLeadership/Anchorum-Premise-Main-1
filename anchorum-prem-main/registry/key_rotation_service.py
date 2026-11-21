"""
Plane 1 (kernel/domain/application/governance): Key rotation service for Anchorum-prem.

Provides key rotation orchestration, predecessor chain verification, and audit
event emission for trust-anchor key lifecycle management.

Notes on guarantees and current scope:
- Rotation calls within a single KeyRotationService instance are serialized via
  an asyncio.Lock; multi-process or distributed coordination must be enforced by
  the underlying SecretManager or backing store.
- Event IDs and digests are computed over canonical JSON (sort_keys=True) using a
  single timestamp captured per event.
- Cryptographic key-backed signing and multi-event hash chaining are marked as
  TODOs where not yet backed by a signing key or journal state store.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from registry.vault_secret_manager import (
    KeyVersion,
    RotationState,
    SecretManager,
    ZarcJournal,
)

logger = logging.getLogger(__name__)

ClockFn = Callable[[], int]


class RotationError(Exception):
    """Base exception for key rotation service failures."""


class AuditEventPublishError(RotationError):
    """Raised when a rotation audit event cannot be published."""


@dataclass
class RotationEvent:
    """Represents a key rotation audit event."""

    event_type: str  # "KEY_ROTATION_INITIATED", "KEY_ROTATION_COMPLETED", "KEY_ROTATION_FAILED"
    stable_event_id: str
    created_at_ns: int
    previous_event_hash: str
    signature: str
    payload: Dict[str, Any] = field(default_factory=dict)


class KeyRotationService:
    """
    Service for orchestrating key rotations with predecessor tracking.

    Coordinates key rotation through SecretManager, verifies predecessor chain
    integrity, and emits structured audit events to an optional event bus.
    """

    def __init__(
        self,
        secret_manager: SecretManager,
        event_bus: Any = None,
        clock_ns: Optional[ClockFn] = None,
    ) -> None:
        self.secret_manager = secret_manager
        self.event_bus = event_bus
        self._clock_ns: ClockFn = clock_ns or ZarcJournal.now_ns
        self._rotation_lock = asyncio.Lock()
        self._last_event_hash: str = ""

    async def initiate_rotation(
        self,
        new_private_key_ref: str,
        new_public_key: bytes,
    ) -> RotationState:
        """
        Initiate a key rotation and record a completion or failure audit event.

        Raises RotationError (or AuditEventPublishError) if rotation or audit
        publishing fails.
        """
        if not new_private_key_ref:
            raise ValueError("new_private_key_ref must be a non-empty string")
        if not new_public_key:
            raise ValueError("new_public_key must be non-empty bytes")

        async with self._rotation_lock:
            logger.info("Initiating key rotation for trust anchor")

            try:
                rotation_state = await self.secret_manager.rotate_keys(
                    new_private_key_ref=new_private_key_ref,
                    new_public_key=new_public_key,
                )

                if rotation_state.status != "completed":
                    error_msg = getattr(rotation_state, "error_message", None) or "unknown error"
                    logger.error(
                        "Key rotation failed with status=%s: %s",
                        rotation_state.status,
                        error_msg,
                    )
                    raise RotationError(f"Rotation failed ({rotation_state.status}): {error_msg}")

                current_version = await self.secret_manager.get_current_key_version()
                predecessor_key_id = (
                    current_version.predecessor_key_id if current_version is not None else None
                )

                logger.info(
                    "Key rotation completed: %s -> %s",
                    rotation_state.current_key_id,
                    rotation_state.new_key_id,
                )

                await self._create_rotation_event(
                    event_type="KEY_ROTATION_COMPLETED",
                    current_key_id=rotation_state.current_key_id,
                    new_key_id=rotation_state.new_key_id,
                    predecessor_key_id=predecessor_key_id,
                )

                return rotation_state

            except AuditEventPublishError:
                raise
            except Exception as exc:
                logger.exception("Key rotation failed with error: %s", exc)
                try:
                    await self._create_rotation_event(
                        event_type="KEY_ROTATION_FAILED",
                        error=str(exc),
                    )
                except AuditEventPublishError as audit_exc:
                    logger.error(
                        "Failed to publish failure audit event after rotation error: %s",
                        audit_exc,
                    )
                raise

    async def verify_key_chain_integrity(
        self,
        key_id: str,
        expected_predecessor: Optional[str],
    ) -> bool:
        """
        Verify that a key exists and passes predecessor/signature chain verification.

        Propagates backend errors rather than masking them as a failed verification.
        """
        if not key_id:
            return False

        current_version = await self.secret_manager.get_current_key_version()
        if current_version is not None and key_id == current_version.key_id:
            return await self.secret_manager.verify_signature_chain(
                key_id=key_id,
                expected_predecessor=expected_predecessor,
            )

        history = await self.secret_manager.get_key_history()
        key_version = next((k for k in history if k.key_id == key_id), None)
        if key_version is None:
            logger.warning("Key %s not found in history", key_id)
            return False

        return await self.secret_manager.verify_signature_chain(
            key_id=key_id,
            expected_predecessor=expected_predecessor,
        )

    async def get_key_history(self) -> List[Dict[str, Any]]:
        """
        Return serialized key history entries from SecretManager.

        Propagates backend exceptions so callers can distinguish errors from an empty history.
        """
        history = await self.secret_manager.get_key_history()
        history_list: List[Dict[str, Any]] = []

        for version in history:
            history_list.append(
                {
                    "key_id": version.key_id,
                    "public_key_hash": hashlib.sha256(version.public_key).hexdigest(),
                    "created_at_ns": version.created_at_ns,
                    "predecessor_key_id": version.predecessor_key_id,
                    "signature_chain_hash": version.signature_chain_hash,
                }
            )

        return history_list

    async def rollback_to_predecessor(self, target_key_id: str) -> KeyVersion:
        """
        Validate a target key's predecessor chain ahead of rolling back.

        Raises LookupError if the target or predecessor version is missing,
        RotationError if chain verification fails, or NotImplementedError until
        predecessor key retrieval and rotation are implemented.
        """
        history = await self.secret_manager.get_key_history()
        target_version = next((k for k in history if k.key_id == target_key_id), None)

        if target_version is None:
            raise LookupError(f"Target key {target_key_id} not found in history")

        predecessor_id = target_version.predecessor_key_id
        if predecessor_id is None:
            raise RotationError(f"Cannot roll back from {target_key_id}: no predecessor_key_id")

        predecessor_version = next((k for k in history if k.key_id == predecessor_id), None)
        if predecessor_version is None:
            raise LookupError(f"Predecessor key {predecessor_id} not found in history")

        is_valid = await self.verify_key_chain_integrity(
            key_id=predecessor_id,
            expected_predecessor=predecessor_version.predecessor_key_id,
        )
        if not is_valid:
            raise RotationError(f"Predecessor key {predecessor_id} failed chain integrity check")

        # TODO: Retrieve predecessor key reference/material and perform an explicit
        # rotation back to predecessor_version rather than mutating history in place.
        raise NotImplementedError(
            f"Rollback to predecessor {predecessor_id} is not yet implemented"
        )

    async def _create_rotation_event(
        self,
        event_type: str,
        **kwargs: Any,
    ) -> Optional[RotationEvent]:
        """Build, digest, and publish a rotation audit event using a single timestamp."""
        timestamp_ns = self._clock_ns()
        payload: Dict[str, Any] = {
            "event_type": event_type,
            "timestamp_ns": timestamp_ns,
            **kwargs,
        }

        canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        previous_hash = self._last_event_hash
        event_id = hashlib.sha256(
            previous_hash.encode("utf-8") + b":" + canonical_payload
        ).hexdigest()[:16]
        signature = self._compute_signature(payload, previous_hash=previous_hash)

        event = RotationEvent(
            event_type=event_type,
            stable_event_id=event_id,
            created_at_ns=timestamp_ns,
            previous_event_hash=previous_hash,
            signature=signature,
            payload=payload,
        )

        if self.event_bus is not None:
            try:
                await self.event_bus.publish(event)
            except Exception as exc:
                raise AuditEventPublishError(f"Failed to publish {event_type} event: {exc}") from exc

        self._last_event_hash = hashlib.sha256(
            f"{event.stable_event_id}:{event.created_at_ns}:{event.signature}".encode("utf-8")
        ).hexdigest()

        return event

    def _compute_signature(self, payload: Dict[str, Any], previous_hash: str = "") -> str:
        """
        Compute a deterministic digest for an event payload.

        TODO: Replace with an asymmetric/HMAC signature using the active signing key
        once key-signing integration is wired into this plane.
        """
        envelope = {
            "previous_event_hash": previous_hash,
            "payload": payload,
        }
        canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


class KeyRotationOrchestrator:
    """
    Facade over KeyRotationService returning plain dictionaries for callers/APIs.
    """

    def __init__(
        self,
        secret_manager: SecretManager,
        event_bus: Any = None,
        clock_ns: Optional[ClockFn] = None,
    ) -> None:
        self.rotation_service = KeyRotationService(
            secret_manager=secret_manager,
            event_bus=event_bus,
            clock_ns=clock_ns,
        )

    async def rotate_keys(
        self,
        new_private_key_ref: str,
        new_public_key: bytes,
    ) -> Dict[str, Any]:
        """Run a key rotation and return a structured status dictionary."""
        try:
            rotation_state = await self.rotation_service.initiate_rotation(
                new_private_key_ref=new_private_key_ref,
                new_public_key=new_public_key,
            )

            return {
                "status": "success",
                "current_key_id": rotation_state.current_key_id,
                "new_key_id": rotation_state.new_key_id,
                "rotation_completed_at_ns": rotation_state.rotation_completed_at_ns,
                "key_history": await self.rotation_service.get_key_history(),
            }

        except Exception as exc:
            logger.error("Orchestrator rotate_keys failed: %s", exc)
            return {
                "status": "failed",
                "error": str(exc),
            }

    async def verify_chain(
        self,
        key_id: str,
        expected_predecessor: Optional[str],
    ) -> bool:
        """Verify signature chain integrity for a key."""
        return await self.rotation_service.verify_key_chain_integrity(
            key_id=key_id,
            expected_predecessor=expected_predecessor,
        )

    async def get_status(self) -> Dict[str, Any]:
        """Return current key rotation status and history."""
        try:
            history = await self.rotation_service.get_key_history()
            return {
                "status": "ok",
                "current_key_id": history[-1]["key_id"] if history else None,
                "key_count": len(history),
                "history": history,
            }
        except Exception as exc:
            logger.error("Failed to get rotation status: %s", exc)
            return {
                "status": "error",
                "error": str(exc),
            }
