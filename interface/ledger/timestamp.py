"""Local RFC 3161 Timestamp Authority (Trust Engine).

This module provides cryptographic proof that a case snapshot existed at a
specific time, without relying on the internet or external blockchains.
It shells out to OpenSSL's ts command, using a local TSA certificate.

The generated .tsr file can be verified by anyone holding the CA certificate
*and* the TSA signer certificate, using standard OpenSSL tools. The signer
certificate is not embedded in the response by `openssl ts -reply`, so a
verifier must be given it explicitly (`-untrusted`); `verify()` below does that.
"""
import subprocess
from pathlib import Path

class TimestampError(Exception):
    """Raised when timestamping or verification fails."""

def claim_tsa_owner(tsa_dir: Path, storage_root: Path) -> None:
    """Verify the TSA certs belong to this deployment, or claim a legacy pair.

    The exported .tsr carries the signer certificate. Two deployments that
    share a TSA pair would produce proofs that are indistinguishable at the
    certificate level. §F requires per-client isolation of the TSA signing
    material, alongside the audit chain and data boundary.

    Writes a .deployment_owner marker derived from sha256(storage_root) on
    first call for a deployment with certs present. On subsequent calls, a
    mismatch means another deployment's TSA directory was copied into place;
    refuses to proceed. Legacy installs (cert, no marker) are claimed once
    with a stderr warning. Fresh installs (no cert) are a no-op.
    """
    import hashlib
    import sys

    tsa_dir = Path(tsa_dir)
    owner = tsa_dir / ".deployment_owner"
    deployment_id = hashlib.sha256(
        str(Path(storage_root).resolve()).encode()
    ).hexdigest()[:16]

    if owner.exists():
        recorded = owner.read_text().strip()
        if recorded != deployment_id:
            raise TimestampError(
                f"TSA pair at {tsa_dir} belongs to a different deployment "
                f"(marker {recorded!r}, this deployment {deployment_id!r}). "
                f"Refusing to sign with a certificate issued by another "
                f"deployment. If this install accidentally received another "
                f"client's TSA directory, delete {tsa_dir} and restart to "
                f"generate a fresh pair."
            )
        return

    if (tsa_dir / "ca.crt").exists():
        tsa_dir.mkdir(parents=True, exist_ok=True)
        owner.write_text(deployment_id + "\n")
        print(
            f"WARN: claimed TSA at {tsa_dir} for deployment {deployment_id}.",
            file=sys.stderr,
        )


def stamp_bytes(data: bytes, out_dir: Path, tsa_dir: Path = Path("var/tsa"), filename: str = "snapshot.alp") -> Path:
    """Write data to out_dir/filename and create a .tsr timestamp response."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # §F: enforce per-deployment TSA ownership before signing.
    claim_tsa_owner(tsa_dir, tsa_dir.parent)

    snapshot_path = out_dir / filename
    snapshot_path.write_bytes(data)
    
    tsr_path = out_dir / (filename + ".tsr")
    
    config = tsa_dir / "tsa.cnf"
    if not config.exists():
        raise TimestampError(f"TSA config not found at {config}. Run the setup script.")

    cmd = [
        "openssl", "ts", "-query",
        "-data", str(snapshot_path),
        "-sha256",
        "-no_nonce",
        "-out", str(tsr_path) + ".query"
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        
        cmd_reply = [
            "openssl", "ts", "-reply",
            "-config", str(config),
            "-queryfile", str(tsr_path) + ".query",
            "-out", str(tsr_path)
        ]
        subprocess.run(cmd_reply, check=True, capture_output=True)
        
        # Clean up query file
        Path(str(tsr_path) + ".query").unlink(missing_ok=True)
        
        return tsr_path
    except subprocess.CalledProcessError as e:
        raise TimestampError(f"OpenSSL ts failed: {e.stderr.decode()}") from e

def verify(
    tsr_path: Path,
    data_path: Path,
    ca_cert_path: Path = Path("var/tsa/ca.crt"),
    tsa_cert_path: Path | None = None,
) -> bool:
    """Verify a .tsr against the original data, the CA cert and the signer cert.

    The signer certificate has to be supplied separately: `openssl ts -reply`
    does not embed it in the response, so verification without it fails with
    "PKCS7_get0_signers: signer certificate not found". Defaults to tsa.crt
    sitting next to the CA certificate.
    """
    if not tsr_path.exists() or not data_path.exists():
        return False

    signer = Path(tsa_cert_path) if tsa_cert_path else Path(ca_cert_path).parent / "tsa.crt"

    cmd = [
        "openssl", "ts", "-verify",
        "-in", str(tsr_path),
        "-data", str(data_path),
        "-CAfile", str(ca_cert_path),
        "-no_nonce"
    ]
    if signer.exists():
        cmd += ["-untrusted", str(signer)]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False
