"""
Plane 1 (kernel/domain/application/governance): Registry for secret management.

Provides deterministic secret management and key rotation primitives for
Anchorum-prem, including predecessor tracking and audit event chaining.

Import behavior:
- Importing this package performs no clock or journal initialization side effects.
- Callers should supply explicit configuration, clients, and clocks during
  service/journal construction or bootstrap.
"""

from registry.key_rotation_service import (
    AuditEventPublishError,
    KeyRotationOrchestrator,
    KeyRotationService,
    RotationError,
    RotationEvent,
)
from registry.vault_secret_manager import (
    AWSSecretsManager,
    KeyVersion,
    RotationState,
    SecretManager,
    VaultSecretManager,
    ZarcJournal,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "ZarcJournal",
    "SecretManager",
    "KeyVersion",
    "RotationState",
    "VaultSecretManager",
    "AWSSecretsManager",
    "KeyRotationService",
    "KeyRotationOrchestrator",
    "RotationEvent",
    "RotationError",
    "AuditEventPublishError",
]
