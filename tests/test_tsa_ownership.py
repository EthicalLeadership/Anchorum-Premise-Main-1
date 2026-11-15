"""Per-deployment TSA ownership (§F).

The exported .tsr carries the signer certificate. Two deployments sharing a
TSA pair would make one client's proof appear issued by another's
infrastructure. claim_tsa_owner() enforces this by writing a marker derived
from the deployment's storage_root, and refusing to proceed if the marker
belongs to a different deployment.
"""
import pytest
from pathlib import Path
from interface.ledger.timestamp import claim_tsa_owner, TimestampError


def _fake_tsa(tsa_dir: Path) -> None:
    tsa_dir.mkdir(parents=True, exist_ok=True)
    (tsa_dir / "ca.crt").write_text(
        "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n"
    )


def test_claims_legacy_tsa(tmp_path, capsys):
    """TSA dir with cert but no marker is claimed once with a warning."""
    tsa_dir = tmp_path / "tsa"
    _fake_tsa(tsa_dir)
    claim_tsa_owner(tsa_dir, tmp_path / "deployment")
    marker = (tsa_dir / ".deployment_owner").read_text().strip()
    assert len(marker) == 16
    assert "claimed TSA" in capsys.readouterr().err


def test_refuses_mismatched_tsa(tmp_path):
    """Core §F control: a copy from another deployment must fail loudly."""
    tsa_dir = tmp_path / "tsa"
    _fake_tsa(tsa_dir)
    claim_tsa_owner(tsa_dir, tmp_path / "deployment-A")
    with pytest.raises(TimestampError, match="belongs to a different deployment"):
        claim_tsa_owner(tsa_dir, tmp_path / "deployment-B")


def test_idempotent_for_same_deployment(tmp_path):
    """Repeated boots for the same deployment do not raise."""
    tsa_dir = tmp_path / "tsa"
    _fake_tsa(tsa_dir)
    claim_tsa_owner(tsa_dir, tmp_path / "deployment")
    claim_tsa_owner(tsa_dir, tmp_path / "deployment")
    claim_tsa_owner(tsa_dir, tmp_path / "deployment")


def test_fresh_install_noop(tmp_path):
    """No certs yet: nothing to claim, no marker written, no error."""
    tsa_dir = tmp_path / "tsa"
    claim_tsa_owner(tsa_dir, tmp_path / "deployment")
    assert not (tsa_dir / ".deployment_owner").exists()
