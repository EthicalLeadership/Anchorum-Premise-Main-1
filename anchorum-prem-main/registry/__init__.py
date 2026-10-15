"""
Plane 1 (kernel/domain/application/governance): Registry for secret management.

This package provides deterministic secret management with key rotation capabilities
for Anchorum-prem, including predecessor tracking and signature chain integrity.
"""

from registry.zarc_journal import ZarcJournal
from registry.vault_secret_manager import (
    SecretManager, KeyVersion, RotationState,
    VaultSecretManager, AWSSecretsManager
)
from registry.key_rotation_service import (
    KeyRotationService, KeyRotationOrchestrator, RotationEvent
)

__all__ = [
    'ZarcJournal',
    'SecretManager',
    'KeyVersion',
    'RotationState',
    'VaultSecretManager',
    'AWSSecretsManager',
    'KeyRotationService',
    'KeyRotationOrchestrator',
    'RotationEvent'
]

# Initialize monotonic clock on import
ZarcJournal.now_ns()
