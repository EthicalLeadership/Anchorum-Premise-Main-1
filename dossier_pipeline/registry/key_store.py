"""Registry key store for managing signing keys in the registry."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, List, Iterator

from .keys import KeyPair, generate_keypair, key_dir


@dataclass
class RegistryKeyStore:
    """In-memory registry of signing keys with optional persistence.
    
    Keys are stored by signer_id and can be loaded from disk or generated on-demand.
    """
    _keys: Dict[str, KeyPair] = field(default_factory=dict)
    _key_dir: Optional[Path] = None
    
    def __post_init__(self):
        """Load keys from disk if a key directory is configured."""
        if self._key_dir is not None and self._key_dir.exists():
            self._load_from_disk()
    
    @property
    def key_dir(self) -> Path:
        """Get or create the key directory."""
        if self._key_dir is None:
            return key_dir()
        return self._key_dir
    
    def _load_from_disk(self):
        """Load all keys from the key directory."""
        d = self.key_dir
        for f in d.glob("*.priv"):
            signer_id = f.stem
            try:
                priv_key = serialization.load_private_key(
                    f.read_bytes(),
                    password=None,
                )
                pub_key = priv_key.public_key()
                self._keys[signer_id] = KeyPair(
                    signer_id=signer_id,
                    private_key=priv_key,
                    public_key=pub_key,
                )
            except Exception as e:
                # Skip corrupted keys
                print(f"Warning: could not load {f}: {e}")
    
    def get(self, signer_id: str) -> Optional[KeyPair]:
        """Get a key by signer_id."""
        return self._keys.get(signer_id)
    
    def add(self, key_pair: KeyPair):
        """Add a key to the store."""
        self._keys[key_pair.signer_id] = key_pair
    
    def remove(self, signer_id: str) -> bool:
        """Remove a key from the store. Returns True if removed."""
        if signer_id in self._keys:
            del self._keys[signer_id]
            return True
        return False
    
    def keys(self) -> Iterator[KeyPair]:
        """Iterate over all keys."""
        return iter(self._keys.values())
    
    def __contains__(self, signer_id: str) -> bool:
        """Check if a key exists."""
        return signer_id in self._keys
    
    def save_to_disk(self):
        """Save all keys to disk."""
        d = self.key_dir
        for key_pair in self._keys.values():
            priv_path = d / f"{key_pair.signer_id}.priv"
            pub_path = d / f"{key_pair.signer_id}.pub"
            
            # Save private key (unencrypted, raw format)
            priv_bytes = key_pair.private_key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
            priv_path.write_bytes(priv_bytes)
            os.chmod(priv_path, 0o600)
            
            # Save public key (raw format)
            pub_bytes = key_pair.public_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
            pub_path.write_bytes(pub_bytes)
            os.chmod(pub_path, 0o644)
    
    def clear(self):
        """Clear all keys from the store."""
        self._keys.clear()