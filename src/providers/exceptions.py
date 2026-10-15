"""Exception classes for Anchorum-prem secret providers.

Plane 1 (kernel/domain/application/governance): deterministic.
No wall-clock. No imports from infrastructure. Fail closed.
"""


class SecretProviderError(Exception):
    """Base exception for all secret provider errors."""
    
    def __init__(self, message: str, provider: str = None) -> None:
        super().__init__(message)
        self.provider = provider or self.__class__.__name__
        self.message = message
    
    def __str__(self) -> str:
        if self.provider:
            return f"[{self.provider}] {self.message}"
        return self.message


class SecretNotFoundError(SecretProviderError):
    """Raised when a secret is not found."""
    
    pass


class AuthenticationError(SecretProviderError):
    """Raised when authentication fails."""
    
    pass


class PermissionError(SecretProviderError):
    """Raised when permission is denied."""
    
    pass


class ConnectionError(SecretProviderError):
    """Raised when connection to vault fails."""
    
    pass


class SecretValidationError(SecretProviderError):
    """Raised when secret data validation fails."""
    
    pass


class SecretRotationError(SecretProviderError):
    """Raised when secret rotation fails."""
    
    pass


class SecretVersionError(SecretProviderError):
    """Raised when version selection fails."""
    
    pass
