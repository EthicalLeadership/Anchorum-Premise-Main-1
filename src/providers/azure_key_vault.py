"""Azure Key Vault Secret Provider for Anchorum-prem.

Plane 1 (kernel/domain/application/governance): deterministic.
No wall-clock. No imports from infrastructure. Fail closed.
"""

import asyncio
import logging
from typing import Any, Dict, Optional

try:
    from azure.identity import DefaultAzureCredential, AzureCliCredential
    from azure.keyvault.secrets import SecretClient
    from azure.core.exceptions import ResourceNotFoundError, HttpResponseError
except ImportError:
    DefaultAzureCredential = None
    AzureCliCredential = None
    SecretClient = None
    ResourceNotFoundError = Exception
    HttpResponseError = Exception
    
from .base import BaseSecretProvider

logger = logging.getLogger(__name__)


class AzureKeyVaultProvider(BaseSecretProvider):
    """Azure Key Vault secret provider implementation.
    
    Features:
    - Multiple authentication methods (Managed Identity, CLI, Service Principal)
    - Secret retrieval by name or ID
    - Version selection support
    - Tag-based filtering
    - Retry policy configuration
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize Azure Key Vault provider.
        
        Args:
            config: Configuration dictionary with keys:
                - vault_url: Azure Key Vault URL (required)
                - auth_method: 'managed_identity', 'cli', or 'service_principal'
                - client_id: Client ID for service principal auth
                - tenant_id: Tenant ID for service principal auth
                - client_secret: Client secret for service principal auth
                - managed_identity_resource: Resource ID for managed identity
                - max_retries: Maximum retry attempts
                - retry_delay: Delay between retries (seconds)
        """
        super().__init__(config)
        self.vault_url = config.get('vault_url')
        self.auth_method = config.get('auth_method', 'managed_identity')
        self.client_id = config.get('client_id')
        self.tenant_id = config.get('tenant_id')
        self.client_secret = config.get('client_secret')
        self.managed_identity_resource = config.get('managed_identity_resource')
        
        # Retry configuration
        self.max_retries = config.get('max_retries', 3)
        self.retry_delay = config.get('retry_delay', 1.0)
        
        self.credential: Optional[Any] = None
        self.client: Optional[SecretClient] = None
    
    async def initialize(self) -> bool:
        """Initialize Azure Key Vault connection."""
        if not self.vault_url:
            raise ValueError("Vault URL is required")
            
        try:
            # Create credential based on auth method
            self.credential = await self._create_credential()
            
            # Create SecretClient
            self.client = SecretClient(
                url=self.vault_url,
                credential=self.credential
            )
            
            self._initialized = True
            logger.info(f"Azure Key Vault provider initialized at {self.vault_url}")
            return True
            
        except Exception as e:
            await self._handle_error(e, "initialize")
            return False
    
    async def _create_credential(self) -> Any:
        """Create authentication credential based on method."""
        if self.auth_method == 'managed_identity':
            # Managed Identity (default for Azure VMs/App Service)
            try:
                from azure.identity import DefaultAzureCredential
                
                credential = DefaultAzureCredential(
                    managed_identity_resource=self.managed_identity_resource
                )
                
                logger.info("Using Managed Identity authentication")
                return credential
                
            except ImportError:
                raise ImportError("azure-identity library required for managed identity")
            
        elif self.auth_method == 'cli':
            # Azure CLI authentication (for local development)
            try:
                from azure.identity import AzureCliCredential
                
                credential = AzureCliCredential()
                
                logger.info("Using Azure CLI authentication")
                return credential
                
            except ImportError:
                raise ImportError("azure-identity library required for CLI auth")
            
        elif self.auth_method == 'service_principal':
            # Service Principal authentication
            if not (self.client_id and self.tenant_id and self.client_secret):
                raise ValueError("Client ID, tenant ID, and secret required for service principal")
            
            try:
                from azure.identity import ClientSecretCredential
                
                credential = ClientSecretCredential(
                    tenant_id=self.tenant_id,
                    client_id=self.client_id,
                    client_secret=self.client_secret
                )
                
                logger.info("Using Service Principal authentication")
                return credential
                
            except ImportError:
                raise ImportError("azure-identity library required for service principal auth")
            
        else:
            raise ValueError(f"Unknown auth method: {self.auth_method}")
    
    async def get_secret(
        self,
        identifier: str,
        version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Retrieve a secret from Azure Key Vault.
        
        Args:
            identifier: Secret name or ID
            version: Specific version ID (optional)
            
        Returns:
            Dictionary with 'value' and metadata
            
        Raises:
            SecretNotFoundError: If secret doesn't exist
            AuthenticationError: If credentials invalid
        """
        if not self.client or not self._initialized:
            raise RuntimeError("Provider not initialized")
        
        try:
            # Get the secret
            if version:
                # Get specific version
                secret = self.client.get_secret(
                    name=identifier,
                    version_id=version
                )
            else:
                # Get latest version
                secret = self.client.get_secret(name=identifier)
            
            return {
                'identifier': identifier,
                'data': secret.value.decode('utf-8') if isinstance(secret.value, bytes) else secret.value,
                'metadata': {
                    'id': secret.id,
                    'version': secret.version,
                    'created_at': secret.created_at.isoformat() if secret.created_at else None,
                    'not_before': secret.not_before.isoformat() if secret.not_before else None
                }
            }
            
        except ResourceNotFoundError:
            raise SecretNotFoundError(f"Secret not found: {identifier}")
        except HttpResponseError as e:
            if e.status_code == 403:
                raise AuthenticationError(f"Access denied: {e}")
            await self._handle_error(e, f"get_secret({identifier})")
        except Exception as e:
            await self._handle_error(e, f"get_secret({identifier})")
    
    async def write_secret(
        self,
        identifier: str,
        data: Dict[str, Any],
        version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Write a secret to Azure Key Vault.
        
        Args:
            identifier: Secret name
            data: Secret value(s) to write
            version: Version tag (not directly supported)
            
        Returns:
            Write confirmation with metadata
        """
        if not self.client or not self._initialized:
            raise RuntimeError("Provider not initialized")
        
        try:
            # Prepare secret value
            secret_value = str(data).encode('utf-8')
            
            # Set tags if provided
            tags = self.config.get('tags', {})
            
            response = self.client.set_secret(
                name=identifier,
                value=secret_value.decode('utf-8'),
                tags=tags
            )
            
            return {
                'identifier': identifier,
                'status': 'created' if response.created_at else 'updated',
                'metadata': {
                    'id': response.id,
                    'version': response.version,
                    'created_at': response.created_at.isoformat() if response.created_at else None
                }
            }
            
        except HttpResponseError as e:
            if e.status_code == 403:
                raise AuthenticationError(f"Access denied: {e}")
            elif e.status_code == 409:
                raise PermissionError(f"Secret already exists or write conflict: {e}")
            await self._handle_error(e, f"write_secret({identifier})")
        except Exception as e:
            await self._handle_error(e, f"write_secret({identifier})")
    
    async def list_secrets(
        self,
        path: Optional[str] = None,
        limit: int = 100
    ) -> list:
        """List secrets in Azure Key Vault.
        
        Args:
            path: Filter by tag prefix (not directly supported)
            limit: Maximum results
            
        Returns:
            List of secret metadata
        """
        if not self.client or not self._initialized:
            raise RuntimeError("Provider not initialized")
        
        try:
            # Azure Key Vault doesn't support listing secrets directly
            # Need to use list_secret_properties which requires permissions
            from azure.core.paging import ItemPaged
            
            secrets = []
            
            # Get all secret properties
            async for secret in self.client.list_secret_properties_async():
                if limit and len(secrets) >= limit:
                    break
                
                # Filter by path/prefix if specified
                if path and not secret.name.startswith(path):
                    continue
                
                secrets.append({
                    'name': secret.name,
                    'id': secret.id,
                    'created_at': secret.created_at.isoformat() if secret.created_at else None,
                    'not_before': secret.not_before.isoformat() if secret.not_before else None,
                    'tags': dict(secret.tags) if secret.tags else {}
                })
            
            return secrets
            
        except Exception as e:
            await self._handle_error(e, "list_secrets")
    
    async def close(self) -> None:
        """Close Azure Key Vault connection."""
        if self.client:
            self.client = None
        if self.credential:
            self.credential = None
        self._initialized = False
        logger.info("Azure Key Vault provider closed")
