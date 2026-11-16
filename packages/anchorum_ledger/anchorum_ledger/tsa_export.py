"""Bundle the trust material an exported case needs to be verifiable.

A `.tsr` produced by :mod:`interface.ledger.timestamp` is **not** self-contained:
`openssl ts -reply` does not embed the signer certificate, so verifying one
requires both

* the signer certificate (``tsa.crt``), and
* the CA certificate that issued it (``ca.crt``).

`openssl ts -verify` takes the signer via ``-untrusted`` and the CA via
``-CAfile``. An export that ships timestamps without those two files hands the
recipient a proof nobody can check, which defeats the point of exporting
evidence at all.

This module answers one question: which files must join the archive.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

#: Directory under the storage root holding the TSA key material.
TSA_DIR_NAME = "tsa"

#: Directory under the storage root holding per-case timestamp responses.
TIMESTAMPS_DIR_NAME = "timestamps"

#: Prefix for trust material inside the archive, so it is never mistaken for
#: the evidence documents themselves.
TRUST_PREFIX = "trust"

#: Certificates a recipient needs in order to verify. Public material only:
#: the private keys are never exported.
PUBLIC_CERTIFICATES = ("tsa.crt", "ca.crt")

#: The stamped bytes, shipped beside the response they are checked against.
STAMPED_ARTIFACTS = ("snapshot.alp",)

README_ARCNAME = f"{TRUST_PREFIX}/VERIFY_TIMESTAMP.md"


def collect_tsa_artifacts(
    storage_root: str | Path,
    case_keys: Iterable[str | None],
) -> dict[str, Path]:
    """Return ``{arcname: source_path}`` for a case's trust material.

    Only files that exist are returned, so an installation that never
    provisioned a TSA ships nothing rather than empty placeholders. Private
    keys are never included: verification is a public-key operation.
    """
    root = Path(storage_root)
    artifacts: dict[str, Path] = {}

    tsa_dir = root / TSA_DIR_NAME
    for name in PUBLIC_CERTIFICATES:
        candidate = tsa_dir / name
        if candidate.is_file():
            artifacts[f"{TRUST_PREFIX}/{name}"] = candidate

    timestamps_root = root / TIMESTAMPS_DIR_NAME
    for key in case_keys:
        if not key:
            continue
        case_dir = timestamps_root / str(key)
        if not case_dir.is_dir():
            continue
        # The snapshot is the file the timestamp actually covers. Shipping the
        # response without it leaves the recipient with nothing to check
        # against, which is only marginally better than shipping nothing.
        for name in STAMPED_ARTIFACTS:
            candidate = case_dir / name
            if candidate.is_file():
                artifacts[f"{TRUST_PREFIX}/{TIMESTAMPS_DIR_NAME}/{name}"] = candidate
        for response in sorted(case_dir.glob("*.tsr")):
            artifacts[f"{TRUST_PREFIX}/{TIMESTAMPS_DIR_NAME}/{response.name}"] = response

    return artifacts


def verification_readme() -> str:
    """Instructions a recipient can follow without knowing this codebase."""
    return VERIFICATION_README


VERIFICATION_README = """\
# Verifying the timestamps in this pack

This archive contains RFC 3161 timestamp responses under `trust/timestamps/`,
and the two certificates under `trust/` needed to check them.

A timestamp response is **not** self-contained: it does not carry its signer
certificate, so verification needs both files below. Pass the signer with
`-untrusted` and the CA with `-CAfile`.

```sh
openssl ts -verify \\
  -in trust/timestamps/snapshot.alp.tsr \\
  -data trust/timestamps/snapshot.alp \\
  -CAfile trust/ca.crt \\
  -untrusted trust/tsa.crt \\
  -no_nonce
```

`snapshot.alp` is the canonical case snapshot the timestamp covers. It is
included so this check runs without anything else from us. The evidence
documents under `evidence/` are the source material; the snapshot is the
digest-bearing record the timestamp pins.

A successful check prints `Verification: OK` and reports the timestamp time.
`Verification: FAILED` means either the data changed after it was stamped, or
you are using the wrong certificate pair.

What this proves, and what it does not: it proves the stamped bytes existed at
the time the response was issued, as asserted by the holder of the signer key.
It does not prove the contents are true, and it does not prove who held that
key unless you trust the signer certificate by some other means. Verification
shows tamper-evidence, not authorship.

Without `trust/tsa.crt` and `trust/ca.crt`, the timestamps here cannot be
checked by anyone, including the party who produced them.
"""
