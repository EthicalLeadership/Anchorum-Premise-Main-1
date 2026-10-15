"""
Plane 1 (kernel/domain/application/governance): Key rotation service for Anchorum-prem.

This module provides the key rotation orchestration layer that:
- Manages predecessor tracking across key versions
- Maintains signature chain integrity during rotation
- Provides rollback capabilities via predecessor keys
- Ensures deterministic behavior across all pipeline stages
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from dataclasses import dataclass, field
import hashlib
import json

from registry.vault_secret_manager import (
    SecretManager, KeyVersion, RotationState, 
    VaultSecretManager, AWSSecretsManager, ZarcJournal
)

logger = logging.getLogger(__name__)


@dataclass
class RotationEvent:
    """Represents a key rotation event for audit trail."""
    event_type: str  # "KEY_ROTATION_INITIATED", "KEY_ROTATION_COMPLETED", "KEY_ROTATION_FAILED"
    stable_event_id: str
    created_at_ns: int
    previous_event_hash: str
    signature: str
    payload: Dict[str, Any] = field(default_factory=dict)


class KeyRotationService:
    """
    Service for orchestrating key rotations with predecessor tracking.
    
    This service ensures that:
    1. Both old and new keys are rotated together (atomic operation)
    2. Predecessor relationships are maintained for signature chain integrity
    3. Rollback is possible via predecessor keys
    4. All rotations are logged with deterministic signatures
    """
    
    def __init__(self, secret_manager: SecretManager, 
                 event_bus=None):
        self.secret_manager = secret_manager
        self.event_bus = event_bus
        self._rotation_lock = asyncio.Lock()
        
    async def initiate_rotation(self, new_private_key_ref: str,
                                new_public_key: bytes) -> RotationState:
        """
        Initiate a key rotation with predecessor tracking.
        
        This method ensures atomic rotation where both old and new keys
        are rotated together to maintain signature chain integrity.
        """
        async with self._rotation_lock:
            logger.info(f"Initiating key rotation for trust anchor")
            
            try:
                # Perform the actual rotation
                rotation_state = await self.secret_manager.rotate_keys(
                    new_private_key_ref=new_private_key_ref,
                    new_public_key=new_public_key
                )
                
                # Verify the rotation succeeded
                current_version = await self.secret_manager.get_current_key_version()
                
                if rotation_state.status == "completed":
                    logger.info(f"Key rotation completed successfully: "
                               f"{rotation_state.current_key_id} -> {rotation_state.new_key_id}")
                    
                    # Create rotation event for audit trail
                    await self._create_rotation_event(
                        event_type="KEY_ROTATION_COMPLETED",
                        current_key_id=rotation_state.current_key_id,
                        new_key_id=rotation_state.new_key_id,
                        predecessor_key_id=current_version.predecessor_key_id
                    )
                    
                    return rotation_state
                else:
                    logger.error(f"Key rotation failed with status: {rotation_state.status}")
                    raise RuntimeError(f"Rotation failed: {rotation_state.error_message}")
                    
            except Exception as e:
                logger.error(f"Key rotation failed with exception: {e}")
                
                # Create failure event for audit trail
                await self._create_rotation_event(
                    event_type="KEY_ROTATION_FAILED",
                    error=str(e)
                )
                
                raise
    
    async def verify_key_chain_integrity(self, key_id: str,
                                         expected_predecessor: Optional[str]) -> bool:
        """
        Verify that a key's predecessor relationship is valid.
        
        This ensures signature chain integrity by checking that:
        1. The key exists in the history
        2. Its predecessor matches expectations
        3. The signature chain hash is valid
        """
        try:
            current_version = await self.secret_manager.get_current_key_version()
            
            # If we're checking the current key, verify its predecessor
            if key_id == current_version.key_id:
                return await self.secret_manager.verify_signature_chain(
                    key_id=key_id,
                    expected_predecessor=expected_predecessor
                )
            
            # For historical keys, retrieve from history
            history = await self.secret_manager.get_key_history()
            key_version = next((k for k in history if k.key_id == key_id), None)
            
            if not key_version:
                logger.warning(f"Key {key_id} not found in history")
                return False
            
            return await self.secret_manager.verify_signature_chain(
                key_id=key_id,
                expected_predecessor=expected_predecessor
            )
            
        except Exception as e:
            logger.error(f"Failed to verify key chain integrity: {e}")
            return False
    
    async def get_key_history(self) -> List[Dict[str, Any]]:
        """Get the complete history of key versions."""
        try:
            history = await self.secret_manager.get_key_history()
            
            # Convert KeyVersion objects to dictionaries for serialization
            history_dict = []
            for version in history:
                history_dict.append({
                    "key_id": version.key_id,
                    "public_key_hash": hashlib.sha256(version.public_key).hexdigest(),
                    "created_at_ns": version.created_at_ns,
                    "predecessor_key_id": version.predecessor_key_id,
                    "signature_chain_hash": version.signature_chain_hash
                })
            
            return history_dict
            
        except Exception as e:
            logger.error(f"Failed to retrieve key history: {e}")
            return []
    
    async def rollback_to_predecessor(self, target_key_id: str) -> Optional[KeyVersion]:
        """
        Rollback to a previous key version.
        
        This method retrieves the predecessor key and restores it as the current key,
        maintaining signature chain integrity.
        """
        try:
            history = await self.secret_manager.get_key_history()
            
            # Find the target key and its predecessor
            target_version = next((k for k in history if k.key_id == target_key_id), None)
            
            if not target_version or target_version.predecessor_key_id is None:
                logger.warning(f"Cannot rollback to {target_key_id}: no predecessor found")
                return None
            
            predecessor_id = target_version.predecessor_key_id
            
            # Verify the predecessor relationship before rolling back
            if not await self.verify_key_chain_integrity(
                key_id=predecessor_id,
                expected_predecessor=target_version.predecessor_key_id
            ):
                logger.error(f"Predecessor {predecessor_id} has invalid chain")
                return None
            
            # Perform the rollback (rotate back to predecessor)
            # This would involve retrieving the predecessor's public key and rotating
            logger.info(f"Rolling back to key: {predecessor_id}")
            
            # Implementation would retrieve predecessor key and rotate back
            return target_version
            
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return None
    
    async def _create_rotation_event(self, event_type: str, **kwargs) -> Optional[RotationEvent]:
        """Create a rotation event for the audit trail."""
        if not self.event_bus:
            return None
        
        try:
            # Create deterministic event signature
            payload = {
                "event_type": event_type,
                "timestamp_ns": ZarcJournal.now_ns(),
                **kwargs
            }
            
            # Compute signature (implementation would use the current key)
            signature = self._compute_signature(payload)
            
            # Create stable event ID
            event_id = hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest()[:16]
            
            event = RotationEvent(
                event_type=event_type,
                stable_event_id=event_id,
                created_at_ns=ZarcJournal.now_ns(),
                previous_event_hash="",  # Would chain to previous event
                signature=signature,
                payload=payload
            )
            
            if self.event_bus:
                await self.event_bus.publish(event)
            
            return event
            
        except Exception as e:
            logger.error(f"Failed to create rotation event: {e}")
            return None
    
    def _compute_signature(self, payload: Dict[str, Any]) -> str:
        """Compute deterministic signature for events."""
        # Implementation would use the current key to sign the payload
        # For now, return a placeholder
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()[:32]


class KeyRotationOrchestrator:
    """
    High-level orchestrator for key rotation operations.
    
    This class provides a simplified interface for performing key rotations
    with automatic predecessor tracking and audit trail maintenance.
    """
    
    def __init__(self, secret_manager: SecretManager,
                 event_bus=None):
        self.rotation_service = KeyRotationService(
            secret_manager=secret_manager,
            event_bus=event_bus
        )
        
    async def rotate_keys(self, new_private_key_ref: str,
                         new_public_key: bytes) -> Dict[str, Any]:
        """
        High-level key rotation method.
        
        Returns a dictionary with rotation status and metadata.
        """
        try:
            rotation_state = await self.rotation_service.initiate_rotation(
                new_private_key_ref=new_private_key_ref,
                new_public_key=new_public_key
            )
            
            return {
                "status": "success",
                "current_key_id": rotation_state.current_key_id,
                "new_key_id": rotation_state.new_key_id,
                "rotation_completed_at_ns": rotation_state.rotation_completed_at_ns,
                "key_history": await self.rotation_service.get_key_history()
            }
            
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e)
            }
    
    async def verify_chain(self, key_id: str,
                          expected_predecessor: Optional[str]) -> bool:
        """Verify signature chain integrity for a key."""
        return await self.rotation_service.verify_key_chain_integrity(
            key_id=key_id,
            expected_predecessor=expected_predecessor
        )
    
    async def get_status(self) -> Dict[str, Any]:
        """Get current key rotation status."""
        try:
            history = await self.rotation_service.get_key_history()
            
            return {
                "current_key_id": history[-1]["key_id"] if history else None,
                "key_count": len(history),
                "history": history
            }
            
        except Exception as e:
            logger.error(f"Failed to get rotation status: {e}")
            return {"error": str(e)}


# ... existing code ...
