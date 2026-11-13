
import os
import stat
from pathlib import Path
import pytest

from interface.security.client_keys import get_or_create_deployment_key


def test_generates_key_if_missing(tmp_path):
    key = get_or_create_deployment_key(tmp_path)
    assert key is not None
    assert (tmp_path / "private_key.pem").exists()
    assert (tmp_path / "public_key.pem").exists()


def test_loads_same_key_on_subsequent_calls(tmp_path):
    key1 = get_or_create_deployment_key(tmp_path)
    key2 = get_or_create_deployment_key(tmp_path)
    
    # Compare public keys to ensure they are the same key
    assert key1.public_key().public_bytes_raw() == key2.public_key().public_bytes_raw()


def test_file_permissions_are_restricted(tmp_path):
    get_or_create_deployment_key(tmp_path)
    priv_stat = os.stat(tmp_path / "private_key.pem")
    # Check that group and other have no permissions (0600)
    assert (priv_stat.st_mode & stat.S_IRWXG) == 0
    assert (priv_stat.st_mode & stat.S_IRWXO) == 0


def test_different_dirs_yield_different_keys(tmp_path):
    dir1 = tmp_path / "client_a"
    dir2 = tmp_path / "client_b"
    key1 = get_or_create_deployment_key(dir1)
    key2 = get_or_create_deployment_key(dir2)
    
    assert key1.public_key().public_bytes_raw() != key2.public_key().public_bytes_raw()
