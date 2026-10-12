# Remediation report — ANCH-2026-10-02-01

**Remediating audit:** `docs/audit/INDEPENDENT_BUILD_AUDIT.md` (ID **ANCH-2026-10-02-01**,
defects F-01…F-19, HIGH = F-01…F-06).
**Repository:** `Anchorumzero_trust-on-Prem`, tree at `298599b`.
**Status of this document:** point-in-time verification record. It states what was
checked, when, and against which commit.

## 1. Method

Every disposition below rests on a command run against the working tree, not on
recollection and not on the audit's own remediation column. The method was, for
each finding: locate the code the finding names, read it, and record the result.
Where a finding is recorded as fixed, the evidence is quoted; where it is not
fixed, the remaining gap is named rather than smoothed over.

Honesty note on scope: several findings (F-07, F-08, F-13, F-14, F-15, F-16)
were closed by other work on this branch before this report was written. They are
recorded as verified here, not as work done for this report.

## 2. Disposition summary

| ID | Sev | Finding | Disposition |
|---|---|---|---|
| F-01 | HIGH | Control signing key has a hard-coded dev default | **FIXED** (residual: key *id* default) |
| F-02 | HIGH | Evidence signer unbound when the secret is unset | **FIXED** |
| F-03 | HIGH | Audit log tamper-evident by hash chain only, no signature or lock | **FIXED** |
| F-04 | HIGH | Anchor omits policy-rejected records from Merkle root and count | **FIXED** |
| F-05 | HIGH | Environment not reproducible | **FIXED** |
| F-06 | HIGH | Supply-chain and egress exposure unmanaged | **FIXED** |
| F-07 | MEDIUM | `dossier_pipeline/README.md` false about its dependencies | **FIXED** |
| F-08 | MEDIUM | Packaging excludes most packages | **FIXED** (residual: `scripts*`) |
| F-09 | MEDIUM | Required data artifact `lexicons/legal-v1.yaml` missing | **RESOLVED** (as v3.1) |
| F-10 | MEDIUM | Two contradictory revocation mechanisms; one orphaned | **OPEN** |
| F-11 | MEDIUM | Persistence paths CWD-relative and non-configurable | **PARTIAL** |
| F-12 | MEDIUM | No CI; secret scanner not enforced | **PARTIAL** |
| F-13 | MEDIUM | Trusted-time not implemented | **FIXED** |
| F-14 | LOW | Stray 7.8 MB artifacts at repo root | **FIXED** |
| F-15 | LOW | Dev/tool artifacts in the tree | **PARTIAL** |
| F-16 | LOW | No version control | **FIXED** |
| F-17 | LOW | Declared vs. installed SQLAlchemy divergence | **FIXED** |
| F-18 | LOW | Weak JWT secrets padded, not strengthened | **OPEN** |
| F-19 | MEDIUM | Repository state ambiguity; project at two paths | **PARTIAL** |

**Counts:** 13 fixed, 4 partial, 2 open.

## 3. Fixed findings

### F-01 — Control-plane signing key (HIGH) — FIXED

`dossier_pipeline/control.py` no longer contains the string `gdc-dev-signing-key`.
It reads the key and refuses to proceed without one:

```
117:        key = os.getenv("GDC_CONTROL_SIGNING_KEY")
120:                "GDC_CONTROL_SIGNING_KEY is not set. Refusing to sign control "
```

Behaviour is asserted by `tests/test_signing_keys_fail_closed.py`
(`ControlSigningKeyFailClosedTests`), so the refusal is now a tested property
rather than a code path nobody exercises.

**Residual.** `control.py:127` still defaults the *key id*:
`os.getenv("GDC_CONTROL_SIGNING_KEY_ID", "local-dev")`. This is a label attached
to a signature, not key material, so it does not weaken the signature — but a
`local-dev` key id on a production chain is a provenance defect, and no test
pins the intended behaviour. Recorded, not fixed, because choosing the policy
(crash vs. warn vs. require an explicit id in non-dev profiles) is a product
decision.

### F-02 — Evidence signer unbound (HIGH) — FIXED

`dossier_pipeline/evidence.py` has a dedicated failure type and no fallback:

```
92:class EvidenceSignerUnbound(RuntimeError):
111:    ``GDC_EVIDENCE_SECRET``. There is deliberately no unbound fallback.
115:        resolved = secret if secret is not None else os.getenv("GDC_EVIDENCE_SECRET")
118:                "No evidence signing secret available. Set GDC_EVIDENCE_SECRET "
```

The old `"unbound"` return is gone, so the empty-key mode — which signed with a
key derivable by anyone — is no longer reachable. Asserted by
`tests/test_signing_keys_fail_closed.py` (`EvidenceSignerFailClosedTests`).

### F-03 — Audit log unsigned and unlocked (HIGH) — FIXED

Both halves the finding asked for are present in
`dossier_pipeline/registry/audit.py`.

*Signing* — the module docstring is now "Hash-chained, **signed** audit log", and
the entry carries a signature and the key that made it:

```
 8:  * ``signature``   - HMAC-SHA256 over the entry identity, keyed by
10:  * ``key_id``      - which key produced the signature
44:import hmac
```

The module documents why the signature is mandatory ("rather than quietly
producing an unsigned chain") and states plainly that it is symmetric, so anyone
holding the key can forge entries (see §7).

*Locking* — the append takes an exclusive advisory file lock:

```
39:    import fcntl
41:    fcntl = None  # type: ignore[assignment]
144:            if fcntl is not None:
145:                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
149:                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
```

`fcntl` is imported defensively and skipped where unavailable (Windows), so the
lock is best-effort by design rather than silently absent. Coverage:
`tests/test_audit_chain_signing.py`; and `scripts/verify_audit_chain.py` runs as
a subprocess in `tests/test_verify_scripts.py`, so a third-party verifier that
fails closed when the key is absent is exercised.

### F-04 — Anchor omitted rejected records (HIGH) — FIXED

`ControlPlane.get_all_records()` no longer filters. It previously dropped records
whose payload had `policy_allowed is False`, and because `export_anchor` and
`verify_anchor` derive the Merkle root and record count from this accessor, the
anchor covered a subset of the chain — a rejected-path record could be altered or
deleted without the anchor noticing. The accessor now returns every committed
record, and the docstring explains why filtering belongs to callers, so the old
behaviour is not re-derived. The only remaining mentions of `policy_allowed` in
the file are the payload write (`:259`) and that docstring (`:537`).

### F-05 — Environment not reproducible (HIGH) — FIXED

`requirements.txt` had open `>=` ranges and no lock, so it resolved to ~185
packages including torch and a full CUDA stack, and no two machines got the same
environment. Now:

- Floors kept, majors bounded (`SQLAlchemy>=2.0,<3`, `cryptography>=42.0,<51`, …).
- `uvicorn` is declared — `interface/server.py` imports it and it was never
  listed, so a clean install could not run the server.
- `pytest` moved to `requirements-dev.txt`, so a runtime install no longer pulls
  the test runner.
- `requirements.lock` pins the 41-package closure the gates were verified
  against.
- CI installs the dev set, checks the lock resolves, and fails on environment
  drift.

The heavyweight ML stack is no longer a dependency at all.

### F-06 — Supply chain and egress unmanaged (HIGH) — FIXED

- `docs/security/EGRESS_INVENTORY.md` enumerates all 8 first-party network call
  sites with their defaults and, critically, records the `grep` method and its
  limits so the list can be re-derived rather than trusted. It identifies the
  `_command` classifier backend as unbounded egress — an arbitrary subprocess
  invoked to obtain a classification.
- `docs/security/SBOM.cdx.json` is a CycloneDX 1.5 SBOM generated from the
  lockfile by `scripts/generate_sbom.py`. That script doubles as a drift check
  (`--check`), so "is this the verified environment?" is answered by CI rather
  than asserted in a README, and it honours `SOURCE_DATE_EPOCH` so the committed
  artifact does not churn on every regeneration.

### F-07 — README false about dependencies (MEDIUM) — FIXED

`dossier_pipeline/README.md:110` now states that core pipeline logic targets the
standard library while "the project as a whole is **not** stdlib-only".

### F-08 — Packaging excludes most packages (MEDIUM) — FIXED

`pyproject.toml` `[tool.setuptools.packages.find]` now includes
`dossier_pipeline*`, `dossier_enforcement*`, `ci*`, `ccsp*`, `evals*`,
`factory*`, `harness*`, `scripts*` — i.e. everything, not just the core.

**Residual.** `scripts/` has no `__init__.py`, so the `scripts*` entry matches no
package and is inert. Harmless, but it is a line that claims something it does
not do.

### F-09 — Missing lexicon artifact (MEDIUM) — RESOLVED

The finding asked for `lexicons/legal-v1.yaml` to be authored, or the
default-loader expectation removed and the test un-skipped. The project took the
second route: `lexicons/legal-v3.1.yaml` ships, and the suite now reports **0
skipped** (was 1 skipped at `tests/test_semantic_adapter.py`). The test no longer
depends on a missing default lexicon — it drives a stub engine and passes an
explicit `lexicon_hash`.

### F-13 — Trusted-time not implemented (MEDIUM) — FIXED

`dossier_pipeline/control.py` now timestamps in UTC from a named source:

```
 34:    return datetime.datetime.now(datetime.timezone.utc).isoformat()
266:            "time_source": TIME_SOURCE_SYSTEM_CLOCK_UTC,
```

Every timestamp carries which clock produced it, which is what the finding asked
for — the audit's complaint was that a timestamp was recorded as if it were
trusted when nothing said where it came from.

### F-14 — Stray artifacts at repo root (LOW) — FIXED

`json`, `sys`, `time` and `uuid` (≈41 MB of ImageMagick PostScript dumps, all
tracked) are gone from the tree and dropped from history on this branch. They are
ignored by absolute root path in `.gitignore`. Verified: all four report `gone`,
and none shadows the stdlib.

### F-16 — No version control (LOW) — FIXED

Git is initialised; the audit is pinned against a commit. `.githooks/pre-commit`
runs the integrity gate and `core.hooksPath` is set to `.githooks`, so the gate
runs on commit rather than only in CI.

### F-17 — SQLAlchemy divergence (LOW) — FIXED

`requirements.txt` bounds a single major (`SQLAlchemy>=2.0,<3`) and
`requirements.lock` pins the exact version, so declared and installed cannot
diverge. `dossier_pipeline/schema.py` imports from `sqlalchemy` /
`sqlalchemy.orm` (including `DeclarativeBase`) consistently with the 2.x line.

## 4. Partially addressed

### F-11 — CWD-relative paths (MEDIUM) — PARTIAL

The paths are now injectable, which is the substance of the finding: the pipeline
takes `output_dir`, `main.py` reads it from `OUTPUT_DIR`, and `anchor_cli.py`
exposes `--output-dir`. But the *defaults* remain CWD-relative:

```
dossier_pipeline/pipeline.py:146:        output_dir: str = "./output",
dossier_pipeline/main.py:257:        "output_dir": env("OUTPUT_DIR", "./output"),
dossier_pipeline/anchor_cli.py:117:    parser.add_argument("--output-dir", default="./output")
```

So a process started from an unexpected directory still writes its custody data
somewhere unintended unless configured. A configured absolute default (or a
startup check that resolves and logs the data directory) would close this.

### F-12 — CI and secret scanner (MEDIUM) — PARTIAL

Half is done: `.github/workflows/integrity.yml` exists and runs the gate
self-test, the gate, the Python suite, `tsc`, `vitest` and the production build;
`.githooks` is active.

The scanner half is not: `grep -rln gitleaks .githooks/ .github/` returns
nothing, so `.gitleaks.toml` is still inert — nobody runs it. A committed
allow-list config that no tool reads provides no protection, and the finding's
point was precisely that a config is not enforcement.

### F-15 — Dev/tool artifacts (LOW) — PARTIAL

`.aider/` is gone. `REPO_MAP.md` is still present in the working tree (56 KB,
git-ignored at `.gitignore:76`). Ignored is not removed: it still ends up in a
naive directory copy or archive of the tree.

### F-19 — Repository state ambiguity (MEDIUM) — PARTIAL

The repository itself is now unambiguous: git-initialised, one canonical branch,
`docs/product` under version control. But the machine-level ambiguity the finding
described is worse, not better — the project exists at many paths under
`/home/kark`, including:

```
/home/kark/anchorum-prem-main(1)          /home/kark/anchorum-prem-main.zip
/home/kark/anchorum-audit-workspace       /home/kark/anchorum-workspace
/home/kark/anchorum-ui-skeleton           /home/kark/anchorum-demo
/home/kark/anchorum-recovered-2026-10-09* (10 bundles)
```

Two of the twelve defects in this repository's own history were caused by a tool
or a human operating on the wrong copy of the tree (see §6). Until the working
copy is `anchorum-prem-main` and the rest are archived, that failure mode stays
live. This is an operational decision about the machine, outside what a commit
can fix.

## 5. Open findings

### F-10 — Two revocation mechanisms, one orphaned (MEDIUM) — OPEN

`dossier_pipeline/registry/keys.py` still implements a file-based revocation
list, still documents it, and is still exported and advertised:

```
registry/__init__.py:2:from . import keys, entry, store, audit, trace
registry/__init__.py:3:__all__ = ["keys", "entry", "store", "audit", "trace"]
registry/keys.py:8:Revocation: append to revoked_keys.txt. Revoked keys can still verify old
registry/keys.py:118:    return (root or DEFAULT_KEY_DIR).parent / "revoked_keys.txt"
```

No first-party caller invokes the file-based path (the only other matches are
unrelated dict `.keys()` calls). So the finding stands exactly as written: two
contradictory mechanisms coexist, one is dead but exported, and the next reader
cannot tell which is authoritative. The fix is a decision, not a patch: either
delete the file-based path and its exports, or mark it deprecated and name the
anchor as the single source of truth.

### F-18 — Weak JWT secrets padded, not strengthened (LOW) — OPEN

The finding's complaint is intact. `auth.py` defines the policy but does not
enforce it:

```
16:MIN_SECRET_KEY_LENGTH = 32
29:def _normalize_secret_key(secret_key: str) -> str:
30:    if len(secret_key) >= MIN_SECRET_KEY_LENGTH:
31:        return secret_key
32:    return sha256(secret_key.encode("utf-8")).hexdigest()
```

A 5-character secret is still accepted, still silently stretched to a 64-character
digest. The digest adds length but no entropy — the secret remains as
guessable as the password typed, and hashing does not slow a dictionary attack
the way a KDF would. There is no minimum-length check anywhere on the input
side. Either reject short secrets at issuance, or derive with a KDF (PBKDF2 /
scrypt / Argon2) and treat the result as a key rather than a password.

## 6. Defects found during remediation (not audit findings)

Corruption was found in the tree that the audit did not report and that no test
caught. It is recorded here because it is evidence about the process, and because
two of the three are the direct subject of F-19.

- **`interface/src/adapter.ts` was duplicated in place** — 1018 lines of which
  lines 1–502 and 503–1004 were byte-identical, with the file's own first line
  spliced mid-expression at the seam. The build was broken (`tsc`: 8 errors
  including an unterminated template literal). Had to be reconstructed and
  verified by rebuilding: the restored CSS bundle hash matched the last
  pre-corruption build byte-for-byte.
- **`dossier_pipeline/contracts.py` was duplicated whole** — size ratio exactly
  2.0000, 17 top-level names declared twice. It still parsed, so Python and every
  test accepted it: two diverging copies of the contract types waiting to drift.
- **`dossier_pipeline/pipeline.py` had an import spliced inside its docstring** —
  `from fpdf import FPDF` sat before the closing `"""`, so `FPDF` was never
  imported while `_generate_pdf` called it; and `_generate_pdf` was indented as a
  method of `IntakeError` instead of `DossierPipeline`. Both are repaired:
  `pipeline.py:17` is a module-level import, `IntakeError` is at `:84`, and
  `_generate_pdf` is correctly at `:236`.

The gate `scripts/check_integrity.py` was rewritten in response: its previous
form had a hard-coded `interface/src/adapter.ts` exception and checked only
`.py/.json/.sh`, and it passed both the doubled `contracts.py` and the spliced
`pipeline.py`. It now runs generic checks over `.py/.sh/.ts/.tsx/.json` and has a
`--selftest` mode that proves each check fires, so the gate can no longer report
success on a tree it did not examine. Wiring that gate into CI and `.githooks` is
what makes the class of corruption detectable rather than merely repaired.

## 7. Residual risk

1. **HMAC is symmetric.** The audit chain's signature (`F-03`) proves an entry
   was made with the shared key; it does not prove *who* held it. Anyone with the
   key can forge a chain. The module says so. Moving to an asymmetric signer with
   an externally witnessed key is explicitly out of scope for this pass and
   should be recorded as accepted risk, not as done.
2. **`_command` classifier backend.** Unbounded subprocess egress (`F-06`).
   Must be disabled outright in restricted deployments, not merely left
   unconfigured.
3. **No enforcement on the key id.** `GDC_CONTROL_SIGNING_KEY_ID` defaults to
   `local-dev` (`F-01` residual).
4. **`F-10` and `F-18` are open** and are both corrective decisions, not
   investigations. Neither has a patch, and neither should be closed by a
   cosmetic change.
5. **The Python interpreter version is not pinned.** The audit ran on 3.12.3;
   these gates ran green on 3.14.4 with pytest 9.x. `requirements.lock` pins the
   packages but not the interpreter, so "same environment" is still only true
   down to the package layer.
6. **`scripts*` in packaging is inert** (`F-08` residual).

## 8. Verification at the time of this report

Run against tree `298599b`:

| Gate | Command | Result |
|---|---|---|
| Integrity self-test | `python3 scripts/check_integrity.py --selftest` | **6/6 PASS** |
| Integrity, all source | `python3 scripts/check_integrity.py --all` | **OK (224 source files)** |
| Lock drift / SBOM | `python3 scripts/generate_sbom.py --check` | **OK — 41 packages, 0 drift** |
| Python suite | `python3 -m pytest -q -p no:cacheprovider` | **302 passed, 0 failed, 0 skipped** |
| Type-check | `npx tsc --noEmit` (in `interface/`) | **exit 0** |
| UI suite | `npx vitest run` (in `interface/`) | **14 files / 75 tests passed** |
| Production build | `npm run build` (in `interface/`) | **exit 0** |

The suite grew from 279 passed + 1 skipped at the original audit to 302 passed
with no skips; the delta includes the new fail-closed signing tests and
`tests/test_interface_api.py`.
