"""Base Secret Provider Interface for Anchorum-prem.

Plane 1 (kernel/domain/application/governance): deterministic.
No wall-clock. No imports from infrastructure. Fail closed.
"""

import abc
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class BaseSecretProvider(abc.ABC):
    """Abstract base class for external secret providers.
    
    All secret providers must implement this interface to ensure
    consistent behavior across different vault implementations.
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize the provider with configuration.
        
        Args:
            config: Provider-specific configuration dictionary.
        """
        self.config = config
        self._initialized = False
        
    @abc.abstractmethod
    async def initialize(self) -> bool:
        """Initialize the provider connection.
        
        Returns:
            True if initialization succeeded, False otherwise.
        """
        pass
    
    @abc.abstractmethod
    async def get_secret(
        self,
        identifier: str,
        version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Retrieve a secret by identifier.
        
        Args:
            identifier: The secret name, path, or ARN.
            version: Optional version identifier (e.g., 'latest', 'v1').
            
        Returns:
            Dictionary containing the secret data and metadata.
            
        Raises:
            SecretNotFoundError: If the secret doesn't exist.
            AuthenticationError: If credentials are invalid.
            ConnectionError: If the vault is unreachable.
        """
        pass
    
    @abc.abstractmethod
    async def write_secret(
        self,
        identifier: str,
        data: Dict[str, Any],
        version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Write or update a secret.
        
        Args:
            identifier: The secret name, path, or ARN.
            data: Secret value(s) to store.
            version: Optional version tag.
            
        Returns:
            Confirmation response with metadata.
            
        Raises:
            AuthenticationError: If credentials are invalid.
            PermissionError: If write access is denied.
        """
        pass
    
    @abc.abstractmethod
    async def list_secrets(
        self,
        path: Optional[str] = None,
        limit: int = 100
    ) -> list:
        """List available secrets in a namespace or path.
        
        Args:
            path: Optional path/namespace to list.
            limit: Maximum number of results.
            
        Returns:
            List of secret metadata dictionaries.
        """
        pass
    
    @abc.abstractmethod
    async def close(self) -> None:
        """Close connections and cleanup resources."""
        pass
    
    async def _handle_error(
        self,
        error: Exception,
        operation: str
    ) -> None:
        """Handle provider-specific errors with graceful degradation.
        
        Args:
            error: The exception that occurred.
            operation: The operation being performed when error occurred.
            
        Logs the error and re-raises if not handled.
        """
        logger.error(
            f"[{self.__class__.__name__}] {operation} failed: {error}",
            exc_info=True
        )
        raise error
    
    async def __aenter__(self) -> 'BaseSecretProvider':
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
