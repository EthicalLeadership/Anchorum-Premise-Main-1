"""
Plane 1 (kernel/domain/application/governance): Key rotation application service.

Coordinates atomic key rotations, rollbacks, revocations, CAS revision checks,
and tamper-linked audit event emission (`RotationEvent`).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

from registry.vault_secret_manager import (
    ConcurrentModificationError,
    KeyStatus,
    RotationState,
    SecretManager,
)
from registry.zarc_journal import ZarcJournal

ClockFn = Callable[[], int]


class EventBus(Protocol):
    """Protocol for publishing audit/rotation events."""

    async def publish(self, event: RotationEvent) -> None: ...


class RotationError(RuntimeError):
    """Raised when a key rotation, rollback, or revocation fails domain invariants."""


class AuditEventPublishError(RuntimeError):
    """Raised when publishing a `RotationEvent` to the event bus fails."""


@dataclass(frozen=True)
class RotationEvent:
    """Immutable audit event emitted for key lifecycle actions."""

    event_type: str
    stable_event_id: str
    created_at_ns: int
    previous_event_hash: str
    signature: str
    payload: Dict[str, Any] = field(default_factory=dict)


class KeyRotationService:
    """Application service orchestrating rotations, rollbacks, revocations, and audit events."""

    def __init__(
        self,
        secret_manager: SecretManager,
        event_bus: Optional[EventBus] = None,
        clock_ns: Optional[ClockFn] = None,
    ) -> None:
        self._secret_manager = secret_manager
        self._event_bus = event_bus
        self._clock_ns: ClockFn = clock_ns if clock_ns is not None else ZarcJournal.now_ns
        self._last_event_hash: str = ""

    def _next_timestamp_ns(self) -> int:
        return int(self._clock_ns())

    def _build_and_chain_event(
        self,
        event_type: str,
        created_at_ns: int,
        payload: Dict[str, Any],
    ) -> RotationEvent:
        stable_event_id = str(uuid.uuid4())
        sig_input = f"{event_type}:{stable_event_id}:{created_at_ns}:{self._last_event_hash}".encode(
            "utf-8"
        )
        signature = hashlib.sha256(sig_input).hexdigest()
        event = RotationEvent(
            event_type=event_type,
            stable_event_id=stable_event_id,
            created_at_ns=created_at_ns,
            previous_event_hash=self._last_event_hash,
            signature=signature,
            payload=payload,
        )
        digest = hashlib.sha256(
            f"{event.stable_event_id}:{event.created_at_ns}:{event.signature}".encode("utf-8")
        ).hexdigest()
        self._last_event_hash = digest
        return event

    async def _emit_event(self, event: RotationEvent) -> None:
        if self._event_bus is None:
            return
        try:
            await self._event_bus.publish(event)
        except Exception as exc:
            raise AuditEventPublishError(f"Failed to publish {event.event_type}") from exc

    async def initiate_rotation(
        self,
        new_private_key_ref: str,
        new_public_key: bytes,
        expected_current_key_id: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> RotationState:
        if not isinstance(new_private_key_ref, str) or not new_private_key_ref.strip():
            raise ValueError("new_private_key_ref must be a non-empty string")
        key_bytes = bytes(new_public_key)
        if not key_bytes:
            raise ValueError("new_public_key must not be empty")

        ts = self._next_timestamp_ns()
        try:
            state = await self._secret_manager.rotate_keys(
                new_private_key_ref=new_private_key_ref,
                new_public_key=key_bytes,
                expected_current_key_id=expected_current_key_id,
                expected_revision=expected_revision,
            )
        except ConcurrentModificationError as exc:
            fail_event = self._build_and_chain_event(
                event_type="KEY_ROTATION_FAILED",
                created_at_ns=ts,
                payload={
                    "timestamp_ns": ts,
                    "reason": str(exc),
                    "conflict": True,
                },
            )
            await self._emit_event(fail_event)
            raise RotationError(str(exc)) from exc

        if state.status != "completed":
            fail_event = self._build_and_chain_event(
                event_type="KEY_ROTATION_FAILED",
                created_at_ns=ts,
                payload={
                    "timestamp_ns": ts,
                    "current_key_id": state.current_key_id,
                    "new_key_id": state.new_key_id,
                    "reason": state.error_message or f"Unexpected status: {state.status}",
                },
            )
            await self._emit_event(fail_event)
            raise RotationError(state.error_message or f"Rotation failed with status {state.status!r}")

        event = self._build_and_chain_event(
            event_type="KEY_ROTATION_COMPLETED",
            created_at_ns=ts,
            payload={
                "timestamp_ns": ts,
                "previous_key_id": state.current_key_id,
                "new_key_id": state.new_key_id,
                "predecessor_key_id": state.predecessor_key_id,
                "revision": state.revision,
            },
        )
        await self._emit_event(event)
        return state

    async def rollback_to_predecessor(
        self,
        key_id: str,
        expected_revision: Optional[int] = None,
    ) -> RotationState:
        if not isinstance(key_id, str) or not key_id.strip():
            raise ValueError("key_id must be a non-empty string")

        history = await self._secret_manager.get_key_history()
        target = next((k for k in history if k.key_id == key_id), None)
        if target is None:
            raise LookupError(f"Key version not found: {key_id!r}")

        if target.predecessor_key_id:
            pred = next((k for k in history if k.key_id == target.predecessor_key_id), None)
            if pred is None:
                raise LookupError(f"Predecessor key not found: {target.predecessor_key_id!r}")
            if pred.status == KeyStatus.REVOKED:
                raise RotationError(f"Cannot roll back to revoked predecessor {pred.key_id!r}")
            grand_pred = pred.predecessor_key_id
            chain_ok = await self._secret_manager.verify_signature_chain(
                key_id=pred.key_id,
                expected_predecessor=grand_pred,
            )
            if not chain_ok:
                raise RotationError(f"Predecessor chain integrity check failed for {pred.key_id!r}")

        ts = self._next_timestamp_ns()
        try:
            state = await self._secret_manager.rollback_to_predecessor(
                key_id=key_id,
                expected_revision=expected_revision,
            )
        except ConcurrentModificationError as exc:
            raise RotationError(str(exc)) from exc
        except ValueError as exc:
            raise RotationError(str(exc)) from exc

        event = self._build_and_chain_event(
            event_type="KEY_ROTATION_ROLLED_BACK",
            created_at_ns=ts,
            payload={
                "timestamp_ns": ts,
                "rolled_back_from_key_id": key_id,
                "restored_key_id": state.new_key_id,
                "predecessor_key_id": state.predecessor_key_id,
                "revision": state.revision,
            },
        )
        await self._emit_event(event)
        return state

    async def revoke_key(
        self,
        key_id: str,
        reason: str,
        expected_revision: Optional[int] = None,
    ) -> KeyStatus:
        if not isinstance(key_id, str) or not key_id.strip():
            raise ValueError("key_id must be a non-empty string")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")

        ts = self._next_timestamp_ns()
        try:
            revoked = await self._secret_manager.revoke_key(
                key_id=key_id,
                reason=reason,
                expected_revision=expected_revision,
            )
        except ConcurrentModificationError as exc:
            raise RotationError(str(exc)) from exc

        event = self._build_and_chain_event(
            event_type="KEY_REVOKED",
            created_at_ns=ts,
            payload={
                "timestamp_ns": ts,
                "key_id": revoked.key_id,
                "reason": reason,
                "revision": revoked.revision,
            },
        )
        await self._emit_event(event)
        return revoked.status

    async def verify_key_chain_integrity(
        self,
        key_id: str,
        expected_predecessor: Optional[str],
    ) -> bool:
        if not key_id:
            return False
        return await self._secret_manager.verify_signature_chain(
            key_id=key_id,
            expected_predecessor=expected_predecessor,
        )

    async def get_key_history(self) -> List[Dict[str, Any]]:
        history = await self._secret_manager.get_key_history()
        return [
            {
                "key_id": item.key_id,
                "predecessor_key_id": item.predecessor_key_id,
                "created_at_ns": item.created_at_ns,
                "signature_chain_hash": item.signature_chain_hash,
                "status": item.status.value,
                "revision": item.revision,
                "revoked_at_ns": item.revoked_at_ns,
                "revocation_reason": item.revocation_reason,
            }
            for item in history
        ]


class KeyRotationOrchestrator:
    """High-level facade returning structured dictionaries for callers/schedulers."""

    def __init__(
        self,
        secret_manager: SecretManager,
        event_bus: Optional[EventBus] = None,
        clock_ns: Optional[ClockFn] = None,
    ) -> None:
        self._secret_manager = secret_manager
        self._service = KeyRotationService(
            secret_manager=secret_manager,
            event_bus=event_bus,
            clock_ns=clock_ns,
        )

    async def rotate_keys(
        self,
        new_private_key_ref: str,
        new_public_key: bytes,
        expected_current_key_id: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            state = await self._service.initiate_rotation(
                new_private_key_ref=new_private_key_ref,
                new_public_key=new_public_key,
                expected_current_key_id=expected_current_key_id,
                expected_revision=expected_revision,
            )
            return {
                "status": "success",
                "current_key_id": state.current_key_id,
                "new_key_id": state.new_key_id,
                "predecessor_key_id": state.predecessor_key_id,
                "revision": state.revision,
            }
        except Exception as exc:
            return {
                "status": "failed",
                "error": str(exc),
            }

    async def rollback_to_predecessor(
        self,
        key_id: str,
        expected_revision: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            state = await self._service.rollback_to_predecessor(
                key_id=key_id,
                expected_revision=expected_revision,
            )
            return {
                "status": "success",
                "rolled_back_from_key_id": key_id,
                "new_key_id": state.new_key_id,
                "predecessor_key_id": state.predecessor_key_id,
                "revision": state.revision,
            }
        except Exception as exc:
            return {
                "status": "failed",
                "error": str(exc),
            }

    async def revoke_key(
        self,
        key_id: str,
        reason: str,
        expected_revision: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            key_status = await self._service.revoke_key(
                key_id=key_id,
                reason=reason,
                expected_revision=expected_revision,
            )
            return {
                "status": "success",
                "key_id": key_id,
                "key_status": key_status.value,
                "revision": self._secret_manager.revision,
            }
        except Exception as exc:
            return {
                "status": "failed",
                "error": str(exc),
            }

    async def get_status(self) -> Dict[str, Any]:
        try:
            current = await self._secret_manager.get_current_key_version()
            history = await self._secret_manager.get_key_history()
            return {
                "status": "ok",
                "current_key_id": current.key_id if current else None,
                "current_key_status": current.status.value if current else None,
                "revision": self._secret_manager.revision,
                "total_versions": len(history),
            }
        except Exception as exc:
            return {
                "status": "error",
                "error": str(exc),
            }
