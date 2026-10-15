#!/usr/bin/env python3
"""Test script for external secret providers.

This script demonstrates basic usage of each provider type.
Run with: python test_secret_providers.py

Note: This is a demonstration script. Actual secrets must be configured
in your environment before running.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.providers import (
    VaultProvider,
    AWSSecretsManagerProvider,
    AzureKeyVaultProvider,
    UnifiedSecretManager,
    SecretNotFoundError,
    AuthenticationError
)


async def test_vault_provider():
    """Test HashiCorp Vault provider."""
    print("\n=== Testing Vault Provider ===")
    
    try:
        # Configuration (update with your actual values)
        config = {
            'url': os.environ.get('VAULT_URL', 'https://vault.internal:8200'),
            'token': os.environ.get('VAULT_TOKEN', ''),
            'method': 'token'
        }
        
        # Skip if no token provided (demo mode)
        if not config['token']:
            print("Skipping Vault test - VAULT_TOKEN not set")
            return
        
        vault = VaultProvider(config)
        
        # Initialize
        initialized = await vault.initialize()
        print(f"Vault provider initialized: {initialized}")
        
        # Test secret retrieval (use a known path or skip)
        if config['token']:
            try:
                secret = await vault.get_secret('test/example')
                print(f"Secret retrieved successfully")
                print(f"  Identifier: {secret['identifier']}")
                print(f"  Data type: {type(secret['data'])}")
            except SecretNotFoundError:
                print("Secret not found (expected for test)")
            except Exception as e:
                print(f"Error retrieving secret: {e}")
        
        await vault.close()
        print("Vault provider closed successfully")
        
    except Exception as e:
        print(f"Vault provider error: {e}")


async def test_aws_provider():
    """Test AWS Secrets Manager provider."""
    print("\n=== Testing AWS Secrets Manager Provider ===")
    
    try:
        config = {
            'region': os.environ.get('AWS_REGION', 'us-east-1'),
            'secret_id': os.environ.get('AWS_SECRET_NAME', ''),
            'iam_role_arn': os.environ.get('AWS_IAM_ROLE_ARN', None)
        }
        
        if not config['secret_id']:
            print("Skipping AWS test - AWS_SECRET_NAME not set")
            return
        
        aws = AWSSecretsManagerProvider(config)
        
        initialized = await aws.initialize()
        print(f"AWS provider initialized: {initialized}")
        
        try:
            secret = await aws.get_secret('test-secret')
            print(f"Secret retrieved successfully")
        except Exception as e:
            print(f"Error retrieving secret (expected): {type(e).__name__}")
        
        await aws.close()
        print("AWS provider closed successfully")
        
    except Exception as e:
        print(f"AWS provider error: {e}")


async def test_azure_provider():
    """Test Azure Key Vault provider."""
    print("\n=== Testing Azure Key Vault Provider ===")
    
    try:
        config = {
            'vault_url': os.environ.get('AZURE_VAULT_URL', ''),
            'auth_method': os.environ.get('AZURE_AUTH_METHOD', 'managed_identity'),
            'client_id': os.environ.get('AZURE_CLIENT_ID', None),
            'tenant_id': os.environ.get('AZURE_TENANT_ID', None),
            'client_secret': os.environ.get('AZURE_CLIENT_SECRET', None)
        }
        
        if not config['vault_url']:
            print("Skipping Azure test - AZURE_VAULT_URL not set")
            return
        
        azure = AzureKeyVaultProvider(config)
        
        initialized = await azure.initialize()
        print(f"Azure provider initialized: {initialized}")
        
        try:
            secret = await azure.get_secret('test-secret')
            print(f"Secret retrieved successfully")
        except Exception as e:
            print(f"Error retrieving secret (expected): {type(e).__name__}")
        
        await azure.close()
        print("Azure provider closed successfully")
        
    except Exception as e:
        print(f"Azure provider error: {e}")


async def test_unified_manager():
    """Test unified secret manager with failover."""
    print("\n=== Testing Unified Secret Manager ===")
    
    try:
        config = {
            'default_provider': 'VaultProvider',
            'providers': [
                {
                    'type': 'vault',
                    'config': {
                        'url': os.environ.get('VAULT_URL', ''),
                        'token': os.environ.get('VAULT_TOKEN', '')
                    }
                },
                {
                    'type': 'aws_secrets_manager',
                    'config': {
                        'region': os.environ.get('AWS_REGION', 'us-east-1'),
                        'secret_id': os.environ.get('AWS_SECRET_NAME', '')
                    }
                }
            ],
            'cache_enabled': True,
            'failover_enabled': True
        }
        
        if not config['providers'][0]['config']['token']:
            print("Skipping unified manager test - no primary provider configured")
            return
        
        manager = UnifiedSecretManager(config)
        
        initialized = await manager.initialize()
        print(f"Unified manager initialized: {initialized}")
        
        try:
            secret = await manager.get_secret('test-secret')
            print(f"Secret retrieved successfully")
        except Exception as e:
            print(f"Error retrieving secret (expected): {type(e).__name__}")
        
        await manager.close()
        print("Unified manager closed successfully")
        
    except Exception as e:
        print(f"Unified manager error: {e}")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("External Secret Providers Test Suite")
    print("=" * 60)
    
    # Run tests sequentially
    await test_vault_provider()
    await test_aws_provider()
    await test_azure_provider()
    await test_unified_manager()
    
    print("\n" + "=" * 60)
    print("Test suite completed")
    print("=" * 60)


if __name__ == '__main__':
    asyncio.run(main())
