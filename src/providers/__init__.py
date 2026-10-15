"""External Secret Providers for Anchorum-prem.

This module provides secure secret retrieval from external vaults:
- HashiCorp Vault
- AWS Secrets Manager  
- Azure Key Vault

All providers implement a common interface for consistent usage across the platform.

Plane 1 (kernel/domain/application/governance): deterministic.
No wall-clock. No imports from infrastructure. Fail closed.
"""

from .base import BaseSecretProvider
from .exceptions import (
    SecretProviderError,
    SecretNotFoundError,
    AuthenticationError,
    PermissionError,
    ConnectionError,
    SecretValidationError,
    SecretRotationError,
    SecretVersionError
)
from .vault import VaultProvider
from .aws_secrets_manager import AWSSecretsManagerProvider
from .azure_key_vault import AzureKeyVaultProvider
from .unified_secret_manager import UnifiedSecretManager

__all__ = [
    # Base classes
    'BaseSecretProvider',
    
    # Exceptions
    'SecretProviderError',
    'SecretNotFoundError',
    'AuthenticationError',
    'PermissionError',
    'ConnectionError',
    'SecretValidationError',
    'SecretRotationError',
    'SecretVersionError',
    
    # Provider implementations
    'VaultProvider',
    'AWSSecretsManagerProvider',
    'AzureKeyVaultProvider',
    
    # Unified interface
    'UnifiedSecretManager'
]


# Example configuration for each provider type
EXAMPLE_CONFIGS = {
    'vault': {
        'type': 'src.providers.vault.VaultProvider',
        'config': {
            'url': 'https://vault.example.com:8200',
            'token': '${VAULT_TOKEN}',
            'method': 'token',  # or 'kubernetes', 'jwt', 'approle'
            'namespace': 'production',
            'mount_point': 'secret',
            'verify_ssl': True,
            'max_retries': 3,
            'retry_delay': 1.0
        }
    },
    'aws_secrets_manager': {
        'type': 'src.providers.aws_secrets_manager.AWSSecretsManagerProvider',
        'config': {
            'region': 'us-east-1',
            'secret_id': '${AWS_SECRET_NAME}',
            'version_stage': 'latest',
            'iam_role_arn': 'arn:aws:iam::123456789012:role/anchorum-secrets',
            'credentials_profile': 'default',
            'max_retries': 3,
            'retry_mode': 'standard'
        }
    },
    'azure_key_vault': {
        'type': 'src.providers.azure_key_vault.AzureKeyVaultProvider',
        'config': {
            'vault_url': 'https://kv.example.com/',
            'auth_method': 'managed_identity',  # or 'cli', 'service_principal'
            'client_id': '${AZURE_CLIENT_ID}',
            'tenant_id': '${AZURE_TENANT_ID}',
            'client_secret': '${AZURE_CLIENT_SECRET}',
            'managed_identity_resource': 'https://vault.azure.net/',
            'max_retries': 3,
            'retry_delay': 1.0
        }
    },
    'unified': {
        'type': 'src.providers.unified_secret_manager.UnifiedSecretManager',
        'config': {
            'default_provider': 'VaultProvider',
            'providers': [
                {'type': 'vault', 'config': {...}},
                {'type': 'aws_secrets_manager', 'config': {...}}
            ],
            'cache_enabled': True,
            'cache_ttl_seconds': 300,
            'failover_enabled': True
        }
    }
}
