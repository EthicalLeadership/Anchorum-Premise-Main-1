import pytest
from pathlib import Path
from interface.ledger.timestamp import stamp_bytes, verify, TimestampError

def test_stamp_and_verify(tmp_path):
    data = b"canonical snapshot bytes"
    tsa_dir = Path("var/tsa")
    
    if not (tsa_dir / "ca.key").exists():
        pytest.skip("TSA certificates not generated")

    tsr_path = stamp_bytes(data, tmp_path, tsa_dir=tsa_dir)
    assert tsr_path.exists()
    assert tsr_path.suffix == ".tsr"
    
    snapshot_path = tmp_path / "snapshot.alp"
    
    # Verify it passes
    assert verify(tsr_path, snapshot_path, tsa_dir / "ca.crt") is True
    
    # Tamper with data, verify it fails
    snapshot_path.write_bytes(b"tampered bytes")
    assert verify(tsr_path, snapshot_path, tsa_dir / "ca.crt") is False
