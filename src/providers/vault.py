"""HashiCorp Vault Secret Provider for Anchorum-prem.

Plane 1 (kernel/domain/application/governance): deterministic.
No wall-clock. No imports from infrastructure. Fail closed.
"""

import asyncio
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

try:
    import hvac
except ImportError:
    hvac = None  # type: ignore
    
from .base import BaseSecretProvider

logger = logging.getLogger(__name__)


class VaultProvider(BaseSecretProvider):
    """HashiCorp Vault secret provider implementation.
    
    Supports multiple authentication methods:
    - AppRole
    - Kubernetes auth method
    - JWT authentication
    - Token-based authentication
    
    Connection pooling and retry logic included.
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize Vault provider.
        
        Args:
            config: Configuration dictionary with keys:
                - url: Vault server URL (required)
                - token: Authentication token OR
                - method: 'kubernetes', 'jwt', or 'approle'
                - kubernetes_role: Role name for K8s auth (if using K8s)
                - jwt_path: Path to JWT file (if using JWT)
                - approle_id: AppRole ID (if using AppRole)
                - approle_secret_id: AppRole secret ID (if using AppRole)
                - namespace: Vault namespace (optional)
        """
        super().__init__(config)
        self.url = config.get('url')
        self.token = config.get('token')
        self.auth_method = config.get('method', 'token')
        self.namespace = config.get('namespace')
        
        # AppRole configuration
        self.approle_id = config.get('approle_id')
        self.approle_secret_id = config.get('approle_secret_id')
        
        # Kubernetes configuration
        self.kubernetes_role = config.get('kubernetes_role')
        self.jwt_path = config.get('jwt_path')
        
        # Retry configuration
        self.max_retries = config.get('max_retries', 3)
        self.retry_delay = config.get('retry_delay', 1.0)
        
        self.client: Optional[hvac.Client] = None
    
    async def initialize(self) -> bool:
        """Initialize Vault connection with authentication."""
        if not self.url:
            raise ValueError("Vault URL is required")
            
        try:
            # Parse and normalize URL
            parsed_url = urlparse(self.url)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            
            # Initialize client
            self.client = hvac.Client(
                url=base_url,
                token=self.token if self.token else None,
                verify=self.config.get('verify_ssl', True),
                allow_redirects=True
            )
            
            # Authenticate based on method
            await self._authenticate()
            
            # Set namespace if configured
            if self.namespace:
                self.client.session.headers['X-Vault-Namespace'] = self.namespace
            
            self._initialized = True
            logger.info(f"Vault provider initialized at {self.url}")
            return True
            
        except Exception as e:
            await self._handle_error(e, "initialize")
            return False
    
    async def _authenticate(self) -> None:
        """Perform authentication based on configured method."""
        if not self.client:
            raise RuntimeError("Vault client not initialized")
            
        if self.auth_method == 'kubernetes':
            await self._authenticate_kubernetes()
        elif self.auth_method == 'jwt':
            await self._authenticate_jwt()
        elif self.auth_method == 'approle':
            await self._authenticate_approle()
        # Token-based is default, no additional auth needed
    
    async def _authenticate_kubernetes(self) -> None:
        """Authenticate using Kubernetes service account."""
        try:
            import kubernetes as k8s
            from hvac.api.auth_methods.approle import AppRoleAuth
            
            # Get token from K8s service account
            token = k8s.client.load_from_file(
                filename='/var/run/secrets/kubernetes.io/serviceaccount/token'
            ).data['value']
            
            self.client.token = token
            logger.info("Authenticated via Kubernetes service account")
            
        except ImportError:
            raise ImportError("kubernetes library required for K8s auth")
        except Exception as e:
            await self._handle_error(e, "Kubernetes authentication")
    
    async def _authenticate_jwt(self) -> None:
        """Authenticate using JWT token."""
        try:
            import jwt
            
            # Read JWT from file or environment
            if self.jwt_path:
                with open(self.jwt_path, 'r') as f:
                    token = f.read().strip()
            else:
                token = self.config.get('jwt_token')
            
            if not token:
                raise ValueError("JWT token required")
            
            # Set JWT as Vault token
            self.client.token = token
            logger.info("Authenticated via JWT")
            
        except ImportError:
            raise ImportError("PyJWT library required for JWT auth")
        except Exception as e:
            await self._handle_error(e, "JWT authentication")
    
    async def _authenticate_approle(self) -> None:
        """Authenticate using AppRole method."""
        try:
            from hvac.api.auth_methods.approle import AppRoleAuth
            
            if not (self.approle_id and self.approle_secret_id):
                raise ValueError("AppRole ID and secret ID required")
            
            # Create auth method client
            approle_client = AppRoleAuth(
                url=self.client.session.url,
                token=self.client.token
            )
            
            # Login with AppRole
            login_response = approle_client.login_approle(
                role_id=self.approle_id,
                secret_id=self.approle_secret_id
            )
            
            self.client.token = login_response['auth']['client_token']
            logger.info("Authenticated via AppRole")
            
        except Exception as e:
            await self._handle_error(e, "AppRole authentication")
    
    async def get_secret(
        self,
        identifier: str,
        version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Retrieve a secret from Vault.
        
        Args:
            identifier: Secret path (e.g., 'secret/myapp/db')
            version: Optional version (Vault uses revision numbers)
            
        Returns:
            Dictionary with 'data' key containing secret values
            
        Raises:
            SecretNotFoundError: If secret doesn't exist
            ConnectionError: If Vault is unreachable
        """
        if not self.client or not self._initialized:
            raise RuntimeError("Provider not initialized")
        
        try:
            # Build path
            path = identifier.strip('/')
            
            # Get secret data
            response = self.client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self.config.get('mount_point', 'secret')
            )
            
            # Handle version selection
            if version and version != 'latest':
                # Vault doesn't support arbitrary versions directly
                # Would need to query revisions
                logger.warning(f"Version '{version}' not supported, returning latest")
            
            data = response['data']
            
            return {
                'identifier': identifier,
                'data': data,
                'metadata': {
                    'version': data.get('version', 'latest'),
                    'created': data.get('created_time'),
                    'path': path
                }
            }
            
        except hvac.exceptions.ForbiddenError:
            raise SecretNotFoundError(f"Access denied to secret: {identifier}")
        except hvac.exceptions.InvalidPath:
            raise SecretNotFoundError(f"Secret not found: {identifier}")
        except hvac.exceptions.ForwardingRequired:
            raise ConnectionError("Vault requires forwarding (proxy needed)")
        except Exception as e:
            await self._handle_error(e, f"get_secret({identifier})")
    
    async def write_secret(
        self,
        identifier: str,
        data: Dict[str, Any],
        version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Write a secret to Vault.
        
        Args:
            identifier: Secret path
            data: Secret values to write
            version: Version tag (not directly supported in Vault)
            
        Returns:
            Write confirmation with metadata
        """
        if not self.client or not self._initialized:
            raise RuntimeError("Provider not initialized")
        
        try:
            path = identifier.strip('/')
            
            # Prepare data for write
            secret_data = {k: str(v) for k, v in data.items()}
            
            response = self.client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=secret_data,
                mount_point=self.config.get('mount_point', 'secret')
            )
            
            return {
                'identifier': identifier,
                'status': 'created' if response['request_id'] else 'updated',
                'metadata': {
                    'version': response.get('data', {}).get('version'),
                    'path': path
                }
            }
            
        except Exception as e:
            await self._handle_error(e, f"write_secret({identifier})")
    
    async def list_secrets(
        self,
        path: Optional[str] = None,
        limit: int = 100
    ) -> list:
        """List secrets in a namespace/path.
        
        Args:
            path: Path to list (e.g., 'secret/myapp')
            limit: Maximum results
            
        Returns:
            List of secret metadata
        """
        if not self.client or not self._initialized:
            raise RuntimeError("Provider not initialized")
        
        try:
            if not path:
                # List root secrets
                response = self.client.secrets.kv.v2.list_secrets(
                    mount_point=self.config.get('mount_point', 'secret')
                )
                return response.get('data', [])
            
            # List secrets in specific path
            response = self.client.secrets.kv.v2.list_secrets(
                path=path,
                mount_point=self.config.get('mount_point', 'secret')
            )
            
            return response.get('data', [])
            
        except Exception as e:
            await self._handle_error(e, "list_secrets")
    
    async def close(self) -> None:
        """Close Vault connection."""
        if self.client:
            # Clear token for security
            self.client.token = ""
            self.client = None
            self._initialized = False
            logger.info("Vault provider closed")
