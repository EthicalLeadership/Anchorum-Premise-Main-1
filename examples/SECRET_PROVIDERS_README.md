# External Secret Providers for Anchorum-prem

This module provides secure secret retrieval from external vaults, enabling Anchorum-prem to work with your existing secret management infrastructure.

## Supported Providers

### HashiCorp Vault
- Token-based authentication
- Kubernetes service account integration
- JWT authentication
- AppRole authentication
- Namespace support for multi-tenancy

### AWS Secrets Manager
- IAM role-based access
- Automatic credential rotation
- Version control with stages (latest, awsv1, etc.)
- Multi-region support

### Azure Key Vault
- Managed Identity authentication
- Service Principal authentication
- Azure CLI authentication
- Soft delete and recovery

## Installation

The providers are included in the Anchorum-prem package. No additional installation is required beyond ensuring the underlying SDKs are available:

```bash
# HashiCorp Vault (if using)
pip install hcp-vault-sdk

# AWS SDK (if using)
pip install boto3 botocore

# Azure SDK (if using)
pip install azure-identity azure-keyvault-secrets
```

## Usage Examples

### Basic Secret Retrieval

```python
from src.providers import VaultProvider, AWSSecretsManagerProvider

# HashiCorp Vault
vault = VaultProvider({
    'url': 'https://vault.internal:8200',
    'token': os.environ['VAULT_TOKEN'],
    'method': 'token'
})

secret = await vault.get_secret('app/config')
print(secret['data']['database_url'])

# AWS Secrets Manager
aws = AWSSecretsManagerProvider({
    'region': 'us-east-1',
    'secret_id': os.environ['AWS_SECRET_NAME'],
    'iam_role_arn': os.environ['AWS_IAM_ROLE_ARN']
})

secret = await aws.get_secret('my-app-secrets')
print(secret['data'])
```

### Using Unified Manager with Failover

```python
from src.providers import UnifiedSecretManager

manager = UnifiedSecretManager({
    'default_provider': 'VaultProvider',
    'providers': [
        {'type': 'vault', 'config': {...}},
        {'type': 'aws_secrets_manager', 'config': {...}}
    ],
    'failover_enabled': True
})

# Automatically uses primary, falls back to secondary if needed
secret = await manager.get_secret('app/config')
```

### Context Manager Usage

```python
from src.providers import VaultProvider

async with VaultProvider({
    'url': 'https://vault.internal:8200',
    'token': os.environ['VAULT_TOKEN']
}) as vault:
    secret = await vault.get_secret('app/config')
    # Connection automatically closed on exit
```

## Configuration Options

### Vault Provider

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `url` | str | - | Vault server URL (required) |
| `token` | str | - | Vault token (for token auth) |
| `method` | str | 'token' | Auth method: token, kubernetes, jwt, approle |
| `namespace` | str | None | Vault namespace for multi-tenancy |
| `mount_point` | str | 'secret' | Secret engine mount point |
| `verify_ssl` | bool | True | Verify SSL certificates |
| `max_retries` | int | 3 | Maximum retry attempts |
| `retry_delay` | float | 1.0 | Delay between retries (seconds) |

### AWS Secrets Manager Provider

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `region` | str | 'us-east-1' | AWS region |
| `secret_id` | str | - | Secret name or ARN (required) |
| `version_stage` | str | 'latest' | Version stage to retrieve |
| `iam_role_arn` | str | None | IAM role to assume |
| `credentials_profile` | str | None | AWS profile for credentials |
| `max_retries` | int | 3 | Maximum retry attempts |

### Azure Key Vault Provider

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `vault_url` | str | - | Key Vault URL (required) |
| `auth_method` | str | 'managed_identity' | Auth method |
| `client_id` | str | None | Client ID for service principal |
| `tenant_id` | str | None | Tenant ID for service principal |
| `client_secret` | str | None | Client secret for service principal |
| `managed_identity_resource` | str | - | Resource ID for managed identity |

## Security Considerations

### 1. Credential Storage
- Never store secrets in code or version control
- Use environment variables or secret management tools
- Rotate credentials regularly (recommended: every 90 days)

### 2. Network Security
- Always use HTTPS/TLS connections
- Verify SSL certificates (verify_ssl: true)
- Use private subnets for vault access
- Implement network segmentation

### 3. Access Control
- Follow least-privilege principle
- Use specific IAM policies rather than admin roles
- Enable audit logging on all providers
- Monitor access patterns for anomalies

### 4. Failover Security
- When enabling failover, ensure secondary providers have appropriate permissions
- Consider using read-only replicas for failover targets
- Implement proper credential rotation across all providers

## Troubleshooting

### Common Issues

**Vault connection refused:**
```bash
# Check vault server is running
curl https://vault.internal:8200/v1/sys/health

# Verify token is valid
curl -H "X-Vault-Token: YOUR_TOKEN" https://vault.internal:8200/v1/sys/auth/token/lookup-self
```

**Authentication failed:**
- Verify token hasn't expired (default TTL: 90 days)
- Check IAM role permissions for AWS
- Validate Azure managed identity assignments

**Secret not found:**
- Verify secret path/name is correct
- Check namespace matches
- Ensure secret exists in the vault

### Debug Mode

Enable debug logging to troubleshoot issues:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

from src.providers import VaultProvider

vault = VaultProvider({
    'url': 'https://vault.internal:8200',
    'token': os.environ['VAULT_TOKEN'],
    'method': 'token'
})

# Initialize with debug
await vault.initialize()
```

## License

This module is part of Anchorum-prem and follows the same license as the main project.

## Support

For issues or questions:
- Check the [Anchorum-prem documentation](https://docs.anchorum-prem.com)
- Review the [HashiCorp Vault documentation](https://developer.hashicorp.com/vault/docs)
- Contact Anchorum support for enterprise assistance
