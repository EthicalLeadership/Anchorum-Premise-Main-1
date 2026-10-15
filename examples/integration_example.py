#!/usr/bin/env python3
"""Integration example: Using external secret providers with Anchorum-prem.

This demonstrates how to integrate the secret providers into your Anchorum-prem
dossier processing workflow.
"""

import asyncio
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.providers import (
    VaultProvider,
    AWSSecretsManagerProvider,
    AzureKeyVaultProvider,
    UnifiedSecretManager,
    SecretNotFoundError,
    AuthenticationError
)


async def load_dossier_secrets(dossier_id: str):
    """Load secrets required for dossier processing from external vault.
    
    Args:
        dossier_id: The dossier identifier
        
    Returns:
        Dictionary of secret values needed for processing
    """
    # Initialize unified manager with failover
    manager = UnifiedSecretManager({
        'default_provider': 'VaultProvider',
        'providers': [
            {
                'type': 'vault',
                'config': {
                    'url': os.environ.get('VAULT_URL', 'https://vault.internal:8200'),
                    'token': os.environ.get('VAULT_TOKEN', ''),
                    'method': 'token'
                }
            },
            {
                'type': 'aws_secrets_manager',
                'config': {
                    'region': os.environ.get('AWS_REGION', 'us-east-1'),
                    'secret_id': os.environ.get('AWS_SECRET_NAME', ''),
                    'iam_role_arn': os.environ.get('AWS_IAM_ROLE_ARN')
                }
            }
        ],
        'cache_enabled': True,
        'failover_enabled': True
    })
    
    try:
        # Load dossier-specific secrets
        secrets = await manager.get_secret(f'dossiers/{dossier_id}/config')
        
        return {
            'database_url': secrets['data'].get('database_url'),
            'api_key': secrets['data'].get('api_key'),
            'encryption_key': secrets['data'].get('encryption_key'),
            'audit_endpoint': secrets['data'].get('audit_endpoint')
        }
        
    except SecretNotFoundError:
        # Use default configuration if dossier-specific secrets not found
        return {
            'database_url': os.environ.get('DATABASE_URL', ''),
            'api_key': os.environ.get('API_KEY', ''),
            'encryption_key': os.environ.get('ENCRYPTION_KEY', ''),
            'audit_endpoint': os.environ.get('AUDIT_ENDPOINT', '')
        }
        
    except AuthenticationError:
        # Failover to secondary provider
        print(f"Authentication failed for dossier {dossier_id}, trying backup")
        raise
        
    finally:
        await manager.close()


async def process_dossier_with_secrets(dossier_path: str, secrets: dict):
    """Process a dossier using loaded secrets.
    
    Args:
        dossier_path: Path to the dossier file
        secrets: Dictionary of secret values
        
    Returns:
        Processing result with audit trail
    """
    # Example: Use encryption key for document processing
    if 'encryption_key' in secrets and secrets['encryption_key']:
        # Encrypt sensitive data before storage
        encrypted_data = encrypt_document(dossier_path, secrets['encryption_key'])
        
        return {
            'status': 'processed',
            'encrypted': True,
            'audit_log': [
                {'action': 'encrypt', 'timestamp': asyncio.get_event_loop().time()},
                {'action': 'store', 'timestamp': asyncio.get_event_loop().time()}
            ]
        }
    else:
        # Process without encryption (for non-sensitive data)
        return {
            'status': 'processed',
            'encrypted': False,
            'audit_log': [
                {'action': 'process', 'timestamp': asyncio.get_event_loop().time()}
            ]
        }


async def main():
    """Main entry point for dossier processing."""
    
    # Example: Process a specific dossier
    dossier_id = "2024-001"
    dossier_path = f"/dossiers/{dossier_id}.json"
    
    print(f"Processing dossier {dossier_id}...")
    
    # Load secrets from vault
    try:
        secrets = await load_dossier_secrets(dossier_id)
        print(f"Loaded secrets for {dossier_id}")
        
        # Process the dossier
        result = await process_dossier_with_secrets(dossier_path, secrets)
        
        print(f"Processing complete: {result['status']}")
        
    except Exception as e:
        print(f"Error processing dossier: {e}")
        # Handle error appropriately (retry, alert, etc.)


if __name__ == '__main__':
    asyncio.run(main())
