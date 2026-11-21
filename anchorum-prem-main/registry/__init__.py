"""
Plane 1 (kernel/domain/application/governance): Registry for secret management.

Provides deterministic secret management and key rotation primitives for
Anchorum-prem, including predecessor tracking and audit event chaining.

Import behavior:
- Importing this package performs no clock or journal initialization side effects.
- Callers should supply explicit configuration, clients, and clocks during
  service/journal construction or bootstrap.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from registry.key_rotation_service import (
    AuditEventPublishError,
    EventBus,
    KeyRotationOrchestrator,
    KeyRotationService,
    RotationError,
    RotationEvent,
)
from registry.vault_secret_manager import (
    AWSSecretsManager,
    ConcurrentModificationError,
    KeyStatus,
    KeyVersion,
    RotationState,
    SecretBackend,
    SecretManager,
    VaultSecretManager,
)
from registry.zarc_journal import JournalRecord, ZarcJournal

try:
    __version__ = version("anchorum-prem-registry")
except PackageNotFoundError:
    __version__ = "0.1.0"

__all__ = [
    "__version__",
    "ZarcJournal",
    "JournalRecord",
    "KeyStatus",
    "ConcurrentModificationError",
    "SecretManager",
    "SecretBackend",
    "KeyVersion",
    "RotationState",
    "VaultSecretManager",
    "AWSSecretsManager",
    "KeyRotationService",
    "KeyRotationOrchestrator",
    "EventBus",
    "RotationEvent",
    "RotationError",
    "AuditEventPublishError",
]
