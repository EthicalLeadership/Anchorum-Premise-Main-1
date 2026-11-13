
"""Per-client deployment key management.

Each deployment must be individualized: a unique Ed25519 keypair per client.
This module handles the lifecycle (generation, secure storage, loading) so the
application does not rely on a shared global key.
"""
from pathlib import Path
import os
import stat

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from interface.ledger.signing import load_private_key_pem, public_key_pem


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    # Ensure the directory is only accessible by the current user
    os.chmod(path, stat.S_IRWXU)


def get_or_create_deployment_key(key_dir: Path) -> Ed25519PrivateKey:
    """Load the deployment's private key, or generate it if it doesn't exist.
    
    The key is stored as a PEM file in `key_dir/private_key.pem` with permissions
    restricted to the owner (0600).
    """
    key_path = key_dir / "private_key.pem"
    
    if key_path.exists():
        pem = key_path.read_bytes()
        return load_private_key_pem(pem)

    # Generate a new key
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    
    _ensure_dir(key_dir)
    key_path.write_bytes(pem)
    os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    
    # Also write the public key for easy access by the client
    pub_path = key_dir / "public_key.pem"
    pub_path.write_text(public_key_pem(private_key))
    os.chmod(pub_path, stat.S_IRUSR | stat.S_IWUSR)
    
    return private_key


def get_or_create_api_key(key_dir: Path) -> str:
    """Generate or load a per-client API key for request authentication."""
    key_path = key_dir / "api_key.txt"
    if key_path.exists():
        return key_path.read_text().strip()
    
    import secrets
    api_key = secrets.token_urlsafe(32)
    _ensure_dir(key_dir)
    key_path.write_text(api_key)
    os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    return api_key
