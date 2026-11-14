"""The export must ship the certificates its timestamps need.

A `.tsr` does not embed its signer certificate, so an archive without
`trust/tsa.crt` and `trust/ca.crt` is unverifiable by the recipient. These tests
pin the bundle's contents and, just as important, the things it must never
contain: private keys, and empty placeholders for a TSA that does not exist.
"""
from pathlib import Path

from interface.ledger.tsa_export import (
    README_ARCNAME,
    collect_tsa_artifacts,
    verification_readme,
)


def _provision(root: Path) -> Path:
    tsa = root / "tsa"
    tsa.mkdir(parents=True)
    (tsa / "tsa.crt").write_text("-----BEGIN CERTIFICATE-----\nsigner\n", encoding="utf-8")
    (tsa / "ca.crt").write_text("-----BEGIN CERTIFICATE-----\nca\n", encoding="utf-8")
    # Private material that must never be bundled.
    (tsa / "tsa.key").write_text("PRIVATE", encoding="utf-8")
    (tsa / "ca.key").write_text("PRIVATE", encoding="utf-8")
    return tsa


def test_bundles_both_certificates(tmp_path):
    _provision(tmp_path)

    artifacts = collect_tsa_artifacts(tmp_path, ["CASE-1"])

    assert artifacts["trust/tsa.crt"].name == "tsa.crt"
    assert artifacts["trust/ca.crt"].name == "ca.crt"


def test_never_bundles_private_keys(tmp_path):
    _provision(tmp_path)

    artifacts = collect_tsa_artifacts(tmp_path, ["CASE-1"])

    assert not [name for name in artifacts if name.endswith(".key")]


def test_case_timestamps_are_included(tmp_path):
    _provision(tmp_path)
    case_dir = tmp_path / "timestamps" / "CASE-1"
    case_dir.mkdir(parents=True)
    (case_dir / "snapshot.alp.tsr").write_bytes(b"tsr-bytes")

    artifacts = collect_tsa_artifacts(tmp_path, ["CASE-1"])

    assert artifacts["trust/timestamps/snapshot.alp.tsr"].read_bytes() == b"tsr-bytes"


def test_other_cases_timestamps_are_not_included(tmp_path):
    _provision(tmp_path)
    other = tmp_path / "timestamps" / "CASE-2"
    other.mkdir(parents=True)
    (other / "snapshot.alp.tsr").write_bytes(b"other-case")

    artifacts = collect_tsa_artifacts(tmp_path, ["CASE-1"])

    assert not [name for name in artifacts if name.endswith(".tsr")]


def test_installation_without_a_tsa_bundles_nothing(tmp_path):
    """No TSA is not an error, and must not produce empty files or a README."""
    assert collect_tsa_artifacts(tmp_path, ["CASE-1"]) == {}


def test_readme_is_present_and_names_both_certificates():
    text = verification_readme()

    assert README_ARCNAME == "trust/VERIFY_TIMESTAMP.md"
    assert "trust/tsa.crt" in text
    assert "trust/ca.crt" in text
    assert "-untrusted" in text, "the verifier needs the signer passed explicitly"
