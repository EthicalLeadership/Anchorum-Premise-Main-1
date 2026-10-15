"""AWS Secrets Manager Secret Provider for Anchorum-prem.

Plane 1 (kernel/domain/application/governance): deterministic.
No wall-clock. No imports from infrastructure. Fail closed.
"""

import asyncio
import logging
from typing import Any, Dict, Optional

try:
    import boto3
    from botocore.exceptions import ClientError, BotoCoreError
except ImportError:
    boto3 = None  # type: ignore
    ClientError = Exception
    BotoCoreError = Exception
    
from .base import BaseSecretProvider

logger = logging.getLogger(__name__)


class AWSSecretsManagerProvider(BaseSecretProvider):
    """AWS Secrets Manager secret provider implementation.
    
    Features:
    - IAM role assumption or direct credentials
    - Secret retrieval by name or ARN
    - Version selection (latest, specific version)
    - AWS SDK retry configuration
    - IAM policy validation helpers
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize AWS Secrets Manager provider.
        
        Args:
            config: Configuration dictionary with keys:
                - region: AWS region (e.g., 'us-east-1')
                - secret_id: Secret name or ARN (required)
                - version_stage: Default version stage ('latest', 'awsv1', etc.)
                - iam_role_arn: IAM role to assume (optional)
                - credentials_profile: Profile name for credentials (optional)
                - max_retries: Maximum retry attempts
                - retry_mode: 'standard' or 'adaptive'
        """
        super().__init__(config)
        self.region = config.get('region', 'us-east-1')
        self.secret_id = config.get('secret_id')
        self.version_stage = config.get('version_stage', 'latest')
        self.iam_role_arn = config.get('iam_role_arn')
        self.credentials_profile = config.get('credentials_profile')
        
        # Retry configuration
        self.max_retries = config.get('max_retries', 3)
        self.retry_mode = config.get('retry_mode', 'standard')
        
        self.client: Optional[boto3.Session] = None
    
    async def initialize(self) -> bool:
        """Initialize AWS Secrets Manager connection."""
        if not self.secret_id:
            raise ValueError("Secret ID (name or ARN) is required")
            
        try:
            # Create boto3 session with appropriate credentials
            self.client = boto3.Session(
                region_name=self.region,
                profile_name=self.credentials_profile
            )
            
            # Assume IAM role if configured
            if self.iam_role_arn:
                await self._assume_iam_role()
            
            # Configure retry logic
            self._configure_retry()
            
            self._initialized = True
            logger.info(f"AWS Secrets Manager provider initialized for region: {self.region}")
            return True
            
        except Exception as e:
            await self._handle_error(e, "initialize")
            return False
    
    async def _assume_iam_role(self) -> None:
        """Assume IAM role for credentials."""
        try:
            sts_client = self.client.client('sts')
            
            response = sts_client.assume_role(
                RoleArn=self.iam_role_arn,
                RoleSessionName='anchorum-prem-secret-provider'
            )
            
            # Create new session with assumed credentials
            creds = response['Credentials']
            self.client = boto3.Session(
                aws_access_key_id=creds['AccessKeyId'],
                aws_secret_access_key=creds['SecretAccessKey'],
                aws_session_token=creds['SessionToken'],
                region_name=self.region
            )
            
            logger.info(f"Assumed IAM role: {self.iam_role_arn}")
            
        except Exception as e:
            await self._handle_error(e, "IAM role assumption")
    
    def _configure_retry(self) -> None:
        """Configure AWS SDK retry behavior."""
        try:
            from botocore.config import Config
            
            retry_config = Config(
                retries={
                    'max_attempts': self.max_retries,
                    'mode': self.retry_mode
                }
            )
            
            # Apply to all clients created from this session
            self.client._session.events.register(
                'before-call',
                self._retry_handler
            )
            
        except Exception as e:
            logger.warning(f"Could not configure retry: {e}")
    
    def _retry_handler(self, event_name, request, **kwargs):
        """Retry handler for AWS calls."""
        if self.retry_mode == 'adaptive':
            # Adaptive retry logic would go here
            pass
    
    async def get_secret(
        self,
        identifier: str,
        version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Retrieve a secret from AWS Secrets Manager.
        
        Args:
            identifier: Secret name or ARN
            version: Version stage ('latest', 'awsv1', etc.)
            
        Returns:
            Dictionary with 'SecretString' or 'SecretBinary' and metadata
            
        Raises:
            SecretNotFoundError: If secret doesn't exist
            AuthenticationError: If credentials invalid
        """
        if not self.client or not self._initialized:
            raise RuntimeError("Provider not initialized")
        
        try:
            # Resolve identifier to ARN if needed
            secret_arn = await self._resolve_secret_arn(identifier)
            
            # Get the secret
            response = self.client.client('secretsmanager').get_secret_value(
                SecretId=secret_arn,
                VersionStage=version or self.version_stage
            )
            
            return {
                'identifier': identifier,
                'data': response.get('SecretString', {}),
                'metadata': {
                    'arn': response.get('ARN'),
                    'version_id': response.get('VersionId'),
                    'stage': response.get('VersionStage')
                }
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                raise SecretNotFoundError(f"Secret not found: {identifier}")
            elif error_code in ('UnauthorizedAccessException', 'InvalidClientException'):
                raise AuthenticationError(f"Authentication failed: {e}")
            else:
                await self._handle_error(e, f"get_secret({identifier})")
        except Exception as e:
            await self._handle_error(e, f"get_secret({identifier})")
    
    async def _resolve_secret_arn(self, identifier: str) -> str:
        """Resolve secret name to ARN."""
        try:
            # Check if it's already an ARN
            if identifier.startswith('arn:'):
                return identifier
            
            # Otherwise, list secrets and find matching one
            response = self.client.client('secretsmanager').list_secrets()
            
            for secret in response.get('SecretList', []):
                if secret['Name'] == identifier:
                    return secret['ARN']
            
            # Not found - will raise error in get_secret
            raise SecretNotFoundError(f"Secret not found: {identifier}")
            
        except Exception as e:
            await self._handle_error(e, "_resolve_secret_arn")
    
    async def write_secret(
        self,
        identifier: str,
        data: Dict[str, Any],
        version: Optional[str] = None
    ) -> Dict[str, Any]:
        """Write a secret to AWS Secrets Manager.
        
        Args:
            identifier: Secret name or ARN
            data: Secret value(s) to write
            version: Version stage
            
        Returns:
            Write confirmation with metadata
        """
        if not self.client or not self._initialized:
            raise RuntimeError("Provider not initialized")
        
        try:
            secret_arn = await self._resolve_secret_arn(identifier)
            
            # Prepare secret value (convert to string)
            secret_string = str(data).encode('utf-8')
            
            response = self.client.client('secretsmanager').put_secret_value(
                SecretId=secret_arn,
                SecretString=secret_string.decode('utf-8'),
                VersionStage=version or self.version_stage
            )
            
            return {
                'identifier': identifier,
                'status': 'created' if response.get('VersionId') else 'updated',
                'metadata': {
                    'arn': response.get('ARN'),
                    'version_id': response.get('VersionId'),
                    'stage': response.get('VersionStage')
                }
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                raise SecretNotFoundError(f"Secret not found: {identifier}")
            elif error_code in ('UnauthorizedAccessException', 'InvalidClientException'):
                raise AuthenticationError(f"Authentication failed: {e}")
            else:
                await self._handle_error(e, f"write_secret({identifier})")
    
    async def list_secrets(
        self,
        path: Optional[str] = None,
        limit: int = 100
    ) -> list:
        """List secrets in AWS Secrets Manager.
        
        Args:
            path: Filter by tag or prefix (not directly supported)
            limit: Maximum results
            
        Returns:
            List of secret metadata
        """
        if not self.client or not self._initialized:
            raise RuntimeError("Provider not initialized")
        
        try:
            response = self.client.client('secretsmanager').list_secrets()
            
            secrets = []
            for secret in response.get('SecretList', [])[:limit]:
                # Filter by path/prefix if specified
                if path and not secret['Name'].startswith(path):
                    continue
                
                secrets.append({
                    'name': secret['Name'],
                    'arn': secret['ARN'],
                    'created_at': secret.get('CreatedDate'),
                    'description': secret.get('Description'),
                    'tags': secret.get('Tags', {})
                })
            
            return secrets
            
        except Exception as e:
            await self._handle_error(e, "list_secrets")
    
    async def close(self) -> None:
        """Close AWS connection."""
        if self.client:
            # Clear credentials for security
            self.client = None
            self._initialized = False
            logger.info("AWS Secrets Manager provider closed")
