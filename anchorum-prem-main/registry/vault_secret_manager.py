"""
Plane 1 (kernel/domain/application/governance): Secret manager contracts and adapters.

Defines domain models (`KeyStatus`, `KeyVersion`, `RotationState`), abstract
`SecretManager` / `SecretBackend` interfaces, CAS concurrency protection, and
`VaultSecretManager` / `AWSSecretsManager` implementations with zero import-time
side effects.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from registry.zarc_journal import ZarcJournal

ClockFn = Callable[[], int]


class KeyStatus(str, Enum):
    """Lifecycle states for a key version in the registry."""

    PENDING = "pending"
    ACTIVE = "active"
    OVERLAP = "overlap"
    RETIRED = "retired"
    REVOKED = "revoked"


class ConcurrentModificationError(RuntimeError):
    """Raised when an optimistic concurrency (CAS) revision or head check fails."""


@dataclass
class KeyVersion:
    """Versioned key metadata and chain provenance record."""

    key_id: str
    public_key: bytes
    private_key_ref: str
    created_at_ns: int
    predecessor_key_id: Optional[str] = None
    signature_chain_hash: str = ""
    status: KeyStatus = KeyStatus.ACTIVE
    revision: int = 0
    revoked_at_ns: Optional[int] = None
    revocation_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RotationState:
    """Result/state snapshot of a key rotation, rollback, or revocation operation."""

    current_key_id: Optional[str]
    new_key_id: Optional[str]
    predecessor_key_id: Optional[str]
    status: str
    revision: int = 0
    error_message: Optional[str] = None


class SecretBackend(ABC):
    """Low-level backend abstraction for secret/key material storage."""

    @abstractmethod
    async def write_key_material(self, key_id: str, private_key_ref: str, public_key: bytes) -> None:
        """Persist or reference key material in the underlying backend."""

    @abstractmethod
    async def read_key_material(self, key_id: str) -> Optional[bytes]:
        """Read stored public/key material for `key_id` if present."""


class SecretManager(ABC):
    """Abstract contract for versioned secret and trust-anchor management."""

    def __init__(self, clock_ns: Optional[ClockFn] = None) -> None:
        if clock_ns is not None and not callable(clock_ns):
            raise TypeError("clock_ns must be callable or None")
        self._clock_ns: ClockFn = clock_ns if clock_ns is not None else ZarcJournal.now_ns
        self._lock = threading.Lock()
        self._key_history: List[KeyVersion] = []
        self._current_key_id: Optional[str] = None
        self._revision: int = 0
        self._rotation_counter: int = 0

    @property
    def revision(self) -> int:
        """Return current monotonic registry revision for optimistic concurrency (CAS)."""
        with self._lock:
            return self._revision

    def _next_timestamp_ns(self) -> int:
        return int(self._clock_ns())

    def _find_key(self, key_id: str) -> Optional[KeyVersion]:
        for item in self._key_history:
            if item.key_id == key_id:
                return item
        return None

    def _assert_cas(
        self,
        expected_current_key_id: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> None:
        if expected_revision is not None and self._revision != expected_revision:
            raise ConcurrentModificationError(
                f"Revision mismatch: expected {expected_revision}, actual {self._revision}"
            )
        if expected_current_key_id is not None and self._current_key_id != expected_current_key_id:
            raise ConcurrentModificationError(
                f"Current key mismatch: expected {expected_current_key_id!r}, "
                f"actual {self._current_key_id!r}"
            )

    @abstractmethod
    async def initialize_trust_anchor(self, root_public_key: bytes) -> KeyVersion:
        """Initialize the root trust anchor (`root-0`)."""

    @abstractmethod
    async def rotate_keys(
        self,
        new_private_key_ref: str,
        new_public_key: bytes,
        expected_current_key_id: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> RotationState:
        """Rotate from the current key to a new key version under CAS checks."""

    @abstractmethod
    async def rollback_to_predecessor(
        self,
        key_id: str,
        expected_revision: Optional[int] = None,
    ) -> RotationState:
        """Restore/activate the valid, non-revoked predecessor of `key_id` under CAS checks."""

    @abstractmethod
    async def revoke_key(
        self,
        key_id: str,
        reason: str,
        expected_revision: Optional[int] = None,
    ) -> KeyVersion:
        """Mark `key_id` as REVOKED (terminal state) and retire active use if needed."""

    @abstractmethod
    async def get_current_key_version(self) -> Optional[KeyVersion]:
        """Return the currently active `KeyVersion`, or None if none is active."""

    @abstractmethod
    async def get_key_history(self) -> List[KeyVersion]:
        """Return a snapshot copy of all recorded `KeyVersion` entries."""

    @abstractmethod
    async def verify_signature_chain(
        self,
        key_id: str,
        expected_predecessor: Optional[str],
    ) -> bool:
        """Verify lineage and chain hash integrity for `key_id`."""


class _InMemoryChainSecretManager(SecretManager):
    """Shared deterministic state machine for in-process Vault and AWS adapters."""

    def __init__(
        self,
        provider_tag: str,
        clock_ns: Optional[ClockFn] = None,
    ) -> None:
        super().__init__(clock_ns=clock_ns)
        self._provider_tag = provider_tag
        self._material_store: Dict[str, bytes] = {}

    async def initialize_trust_anchor(self, root_public_key: bytes) -> KeyVersion:
        key_bytes = bytes(root_public_key)
        if not key_bytes:
            raise ValueError("root_public_key must not be empty")

        with self._lock:
            if self._key_history:
                raise RuntimeError("Trust anchor already initialized")
            ts = self._next_timestamp_ns()
            chain_hash = ZarcJournal.compute_chain_hash(
                predecessor_key_id=None,
                public_key=key_bytes,
                previous_chain_hash="",
            )
            self._revision += 1
            root = KeyVersion(
                key_id="root-0",
                public_key=key_bytes,
                private_key_ref=f"{self._provider_tag}://trust-anchor/root-0",
                created_at_ns=ts,
                predecessor_key_id=None,
                signature_chain_hash=chain_hash,
                status=KeyStatus.ACTIVE,
                revision=self._revision,
                metadata={"provider": self._provider_tag, "role": "trust_anchor"},
            )
            self._material_store[root.key_id] = key_bytes
            self._key_history.append(root)
            self._current_key_id = root.key_id
            return root

    async def rotate_keys(
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

        with self._lock:
            self._assert_cas(
                expected_current_key_id=expected_current_key_id,
                expected_revision=expected_revision,
            )
            if not self._key_history:
                raise RuntimeError("Trust anchor must be initialized before rotating keys")

            prior_current = self._find_key(self._current_key_id) if self._current_key_id else None
            if prior_current is None:
                raise RuntimeError("No current key available to rotate from")
            if prior_current.status == KeyStatus.REVOKED:
                raise RuntimeError(f"Cannot rotate from revoked key {prior_current.key_id!r}")

            ts = self._next_timestamp_ns()
            self._rotation_counter += 1
            new_key_id = f"key-{self._rotation_counter}"
            chain_hash = ZarcJournal.compute_chain_hash(
                predecessor_key_id=prior_current.key_id,
                public_key=key_bytes,
                previous_chain_hash=prior_current.signature_chain_hash,
            )

            # Transition previous active key to OVERLAP (grace window) unless already RETIRED/REVOKED
            if prior_current.status == KeyStatus.ACTIVE:
                prior_current.status = KeyStatus.OVERLAP

            self._revision += 1
            new_version = KeyVersion(
                key_id=new_key_id,
                public_key=key_bytes,
                private_key_ref=new_private_key_ref,
                created_at_ns=ts,
                predecessor_key_id=prior_current.key_id,
                signature_chain_hash=chain_hash,
                status=KeyStatus.ACTIVE,
                revision=self._revision,
                metadata={"provider": self._provider_tag},
            )
            self._material_store[new_key_id] = key_bytes
            self._key_history.append(new_version)
            self._current_key_id = new_key_id

            return RotationState(
                current_key_id=prior_current.key_id,
                new_key_id=new_key_id,
                predecessor_key_id=prior_current.key_id,
                status="completed",
                revision=self._revision,
            )

    async def rollback_to_predecessor(
        self,
        key_id: str,
        expected_revision: Optional[int] = None,
    ) -> RotationState:
        if not isinstance(key_id, str) or not key_id.strip():
            raise ValueError("key_id must be a non-empty string")

        with self._lock:
            self._assert_cas(expected_revision=expected_revision)

            target = self._find_key(key_id)
            if target is None:
                raise LookupError(f"Key version not found: {key_id!r}")
            if not target.predecessor_key_id:
                raise ValueError(f"Key {key_id!r} has no predecessor to roll back to")

            predecessor = self._find_key(target.predecessor_key_id)
            if predecessor is None:
                raise LookupError(f"Predecessor key not found: {target.predecessor_key_id!r}")
            if predecessor.status == KeyStatus.REVOKED:
                raise RuntimeError(
                    f"Cannot roll back to revoked predecessor {predecessor.key_id!r}"
                )

            # Verify chain integrity of predecessor and target
            prior_of_pred = (
                self._find_key(predecessor.predecessor_key_id)
                if predecessor.predecessor_key_id
                else None
            )
            pred_prev_hash = prior_of_pred.signature_chain_hash if prior_of_pred else ""
            expected_pred_hash = ZarcJournal.compute_chain_hash(
                predecessor_key_id=predecessor.predecessor_key_id,
                public_key=predecessor.public_key,
                previous_chain_hash=pred_prev_hash,
            )
            if not hmac.compare_digest(predecessor.signature_chain_hash, expected_pred_hash):
                raise ValueError(f"Predecessor chain hash mismatch for {predecessor.key_id!r}")

            expected_target_hash = ZarcJournal.compute_chain_hash(
                predecessor_key_id=target.predecessor_key_id,
                public_key=target.public_key,
                previous_chain_hash=predecessor.signature_chain_hash,
            )
            if not hmac.compare_digest(target.signature_chain_hash, expected_target_hash):
                raise ValueError(f"Target chain hash mismatch for {target.key_id!r}")

            ts = self._next_timestamp_ns()
            if target.status == KeyStatus.ACTIVE:
                target.status = KeyStatus.RETIRED

            self._rotation_counter += 1
            restored_key_id = f"key-{self._rotation_counter}"
            restored_hash = ZarcJournal.compute_chain_hash(
                predecessor_key_id=predecessor.key_id,
                public_key=predecessor.public_key,
                previous_chain_hash=target.signature_chain_hash,
            )
            self._revision += 1
            restored_version = KeyVersion(
                key_id=restored_key_id,
                public_key=predecessor.public_key,
                private_key_ref=predecessor.private_key_ref,
                created_at_ns=ts,
                predecessor_key_id=predecessor.key_id,
                signature_chain_hash=restored_hash,
                status=KeyStatus.ACTIVE,
                revision=self._revision,
                metadata={
                    "provider": self._provider_tag,
                    "rolled_back_from": target.key_id,
                    "restored_from": predecessor.key_id,
                },
            )
            self._material_store[restored_key_id] = predecessor.public_key
            self._key_history.append(restored_version)
            self._current_key_id = restored_key_id

            return RotationState(
                current_key_id=target.key_id,
                new_key_id=restored_key_id,
                predecessor_key_id=predecessor.key_id,
                status="completed",
                revision=self._revision,
            )

    async def revoke_key(
        self,
        key_id: str,
        reason: str,
        expected_revision: Optional[int] = None,
    ) -> KeyVersion:
        if not isinstance(key_id, str) or not key_id.strip():
            raise ValueError("key_id must be a non-empty string")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")

        with self._lock:
            self._assert_cas(expected_revision=expected_revision)

            target = self._find_key(key_id)
            if target is None:
                raise LookupError(f"Key version not found: {key_id!r}")

            if target.status == KeyStatus.REVOKED:
                return target

            ts = self._next_timestamp_ns()
            self._revision += 1
            target.status = KeyStatus.REVOKED
            target.revoked_at_ns = ts
            target.revocation_reason = reason
            target.revision = self._revision

            if self._current_key_id == key_id:
                self._current_key_id = None

            return target

    async def get_current_key_version(self) -> Optional[KeyVersion]:
        with self._lock:
            if self._current_key_id is None:
                return None
            current = self._find_key(self._current_key_id)
            if current is None or current.status != KeyStatus.ACTIVE:
                return None
            return current

    async def get_key_history(self) -> List[KeyVersion]:
        with self._lock:
            return list(self._key_history)

    async def verify_signature_chain(
        self,
        key_id: str,
        expected_predecessor: Optional[str],
    ) -> bool:
        with self._lock:
            entry = self._find_key(key_id)
            if entry is None:
                return False
            if entry.status == KeyStatus.REVOKED:
                return False
            if entry.predecessor_key_id != expected_predecessor:
                return False

            prev_hash = ""
            if entry.predecessor_key_id is not None:
                pred = self._find_key(entry.predecessor_key_id)
                if pred is None or pred.status == KeyStatus.REVOKED:
                    return False
                prev_hash = pred.signature_chain_hash

            computed = ZarcJournal.compute_chain_hash(
                predecessor_key_id=entry.predecessor_key_id,
                public_key=entry.public_key,
                previous_chain_hash=prev_hash,
            )
            return hmac.compare_digest(entry.signature_chain_hash, computed)


class VaultSecretManager(_InMemoryChainSecretManager):
    """HashiCorp Vault adapter implementing `SecretManager`."""

    def __init__(
        self,
        vault_address: str,
        token: str,
        mount_point: str = "secret",
        clock_ns: Optional[ClockFn] = None,
    ) -> None:
        if not vault_address or not vault_address.strip():
            raise ValueError("vault_address must be non-empty")
        if not token or not token.strip():
            raise ValueError("token must be non-empty")
        super().__init__(provider_tag="vault", clock_ns=clock_ns)
        self.vault_address = vault_address
        self.token = token
        self.mount_point = mount_point


class AWSSecretsManager(_InMemoryChainSecretManager):
    """AWS Secrets Manager / KMS adapter implementing `SecretManager`."""

    def __init__(
        self,
        region_name: str,
        secret_id: str,
        clock_ns: Optional[ClockFn] = None,
    ) -> None:
        if not region_name or not region_name.strip():
            raise ValueError("region_name must be non-empty")
        if not secret_id or not secret_id.strip():
            raise ValueError("secret_id must be non-empty")
        super().__init__(provider_tag="aws", clock_ns=clock_ns)
        self.region_name = region_name
        self.secret_id = secret_id
