"""Unified Secret Manager for Anchorum-prem.

Plane 1 (kernel/domain/application/governance): deterministic.
No wall-clock. No imports from infrastructure. Fail closed.

This module provides a unified interface to work with any secret provider,
with automatic failover and caching support.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union
from abc import ABC

from .base import BaseSecretProvider
from .exceptions import (
    SecretNotFoundError,
    AuthenticationError,
    ConnectionError,
    SecretValidationError
)

logger = logging.getLogger(__name__)


class UnifiedSecretManager:
    """Unified secret manager with provider abstraction and failover.
    
    Features:
    - Provider-agnostic interface
    - Automatic provider selection based on configuration
    - Failover between multiple providers
    - Secret caching with TTL
    - Audit logging for compliance
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize the unified secret manager.
        
        Args:
            config: Configuration dictionary with keys:
                - default_provider: Default provider class name
                - providers: List of provider configurations
                - cache_enabled: Enable caching (default: True)
                - cache_ttl_seconds: Cache TTL in seconds (default: 300)
                - failover_enabled: Enable automatic failover (default: True)
        """
        self.config = config
        self.default_provider = config.get('default_provider', 'VaultProvider')
        self.cache_enabled = config.get('cache_enabled', True)
        self.cache_ttl_seconds = config.get('cache_ttl_seconds', 300)
        self.failover_enabled = config.get('failover_enabled', True)
        
        # Provider instances
        self._providers: List[BaseSecretProvider] = []
        self._active_provider: Optional[BaseSecretProvider] = None
        
        # Cache storage
        self._cache: Dict[str, Dict[str, Any]] = {}
    
    async def initialize(self) -> bool:
        """Initialize all configured providers."""
        try:
            # Create provider instances
            for provider_config in self.config.get('providers', []):
                provider_class_name = provider_config.get('type')
                
                if not provider_class_name:
                    logger.warning("Provider configuration missing 'type' field")
                    continue
                
                # Import and instantiate provider
                module_name, class_name = provider_class_name.rsplit('.', 1)
                module = __import__(f'src.providers.{module_name}', fromlist=[class_name])
                provider_class = getattr(module, class_name)
                
                provider = provider_class(provider_config.get('config', {}))
                
                # Initialize provider
                if await provider.initialize():
                    self._providers.append(provider)
                    logger.info(f"Initialized provider: {provider_class_name}")
            
            # Set default provider as active
            if self._providers:
                self._active_provider = self._providers[0]
            
            return len(self._providers) > 0
            
        except Exception as e:
            await self._handle_error(e, "initialize")
            return False
    
    async def get_secret(
        self,
        identifier: str,
        version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Retrieve a secret using active provider or failover.
        
        Args:
            identifier: Secret name/path/ARN
            version: Optional version
            
        Returns:
            Secret data with metadata
            
        Raises:
            SecretNotFoundError: If secret doesn't exist
            AuthenticationError: If authentication fails
            ConnectionError: If all providers unreachable
        """
        # Check cache first
        if self.cache_enabled:
            cache_key = f"{identifier}:{version or 'latest'}"
            cached = self._cache.get(cache_key, {})
            
            if cached and not self._is_cache_expired(cached):
                logger.debug(f"Cache hit for {identifier}")
                return cached
            
        # Try active provider first
        if self._active_provider:
            try:
                result = await self._active_provider.get_secret(
                    identifier, version
                )
                
                # Cache result
                if self.cache_enabled:
                    self._cache[cache_key] = {
                        'data': result,
                        'expires_at': asyncio.get_event_loop().time() + self.cache_ttl_seconds
                    }
                
                return result
                
            except SecretNotFoundError:
                raise
            except AuthenticationError:
                # Failover on auth error
                if self.failover_enabled and len(self._providers) > 1:
                    logger.info(f"Auth failed on {self._active_provider.__class__.__name__}, trying next provider")
                    await self._failover()
                    
                    if self._active_provider:
                        return await self._active_provider.get_secret(identifier, version)
                raise
            except ConnectionError:
                # Failover on connection error
                if self.failover_enabled and len(self._providers) > 1:
                    logger.info(f"Connection failed on {self._active_provider.__class__.__name__}, trying next provider")
                    await self._failover()
                    
                    if self._active_provider:
                        return await self._active_provider.get_secret(identifier, version)
                raise
            except Exception as e:
                logger.error(f"Unexpected error on {self._active_provider.__class__.__name__}: {e}")
                if self.failover_enabled and len(self._providers) > 1:
                    await self._failover()
                    
                    if self._active_provider:
                        return await self._active_provider.get_secret(identifier, version)
                raise
        
        # No active provider
        raise ConnectionError("No available secret providers")
    
    async def write_secret(
        self,
        identifier: str,
        data: Dict[str, Any],
        version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Write a secret using active provider."""
        if not self._active_provider:
            raise ConnectionError("No active provider available")
        
        try:
            return await self._active_provider.write_secret(
                identifier, data, version
            )
            
        except Exception as e:
            await self._handle_error(e, f"write_secret({identifier})")
            raise
    
    async def list_secrets(
        self,
        path: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List secrets using active provider."""
        if not self._active_provider:
            raise ConnectionError("No active provider available")
        
        try:
            return await self._active_provider.list_secrets(path, limit)
            
        except Exception as e:
            await self._handle_error(e, "list_secrets")
            raise
    
    async def _failover(self) -> None:
        """Failover to next available provider."""
        if not self.failover_enabled or len(self._providers) <= 1:
            return
        
        # Find next available provider
        for provider in self._providers[1:]:
            try:
                # Test connection
                await provider.get_secret('_test', version='latest')
                
                logger.info(f"Failover successful to {provider.__class__.__name__}")
                self._active_provider = provider
                return
                
            except Exception:
                continue
        
        # All providers failed
        logger.error("All providers failed during failover")
    
    def _is_cache_expired(self, cached: Dict[str, Any]) -> bool:
        """Check if cache entry is expired."""
        expires_at = cached.get('expires_at', 0)
        return asyncio.get_event_loop().time() > expires_at
    
    async def _handle_error(
        self,
        error: Exception,
        operation: str
    ) -> None:
        """Handle errors with logging and potential failover."""
        logger.error(f"[UnifiedSecretManager] {operation} failed: {error}", exc_info=True)
        raise error
    
    async def close(self) -> None:
        """Close all provider connections."""
        for provider in self._providers:
            await provider.close()
        
        self._providers.clear()
        self._active_provider = None
        self._cache.clear()
        
        logger.info("Unified secret manager closed")
    
    async def __aenter__(self) -> 'UnifiedSecretManager':
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()


# Factory function for creating unified managers
def create_unified_manager(config: Dict[str, Any]) -> UnifiedSecretManager:
    """Create a unified secret manager from configuration.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Configured UnifiedSecretManager instance
    """
    return UnifiedSecretManager(config)
