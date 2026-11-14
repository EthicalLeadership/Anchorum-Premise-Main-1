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

def stamp_bytes(data: bytes, out_dir: Path, tsa_dir: Path = Path("var/tsa"), filename: str = "snapshot.alp") -> Path:
    """Write data to out_dir/filename and create a .tsr timestamp response."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
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
