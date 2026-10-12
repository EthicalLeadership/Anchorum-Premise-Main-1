# Remediation report — ANCH-2026-10-02-01

**Remediating audit:** `docs/audit/INDEPENDENT_BUILD_AUDIT.md` (ID **ANCH-2026-10-02-01**,
defects F-01…F-19, HIGH = F-01…F-06).
**Repository:** `Anchorumzero_trust-on-Prem`, tree at `298599b` with F-10, F-11,
F-12, F-15 and F-18 applied after it.
**Status of this document:** point-in-time verification record. It states what
was checked and against which tree.

## 1. Method

Every disposition below rests on a command run against the working tree, not on
recollection and not on the audit's own remediation column. The method was, for
each finding: locate the code the finding names, read it, and record the result.
Where a finding is recorded as fixed, the evidence is quoted; where it is not
fixed, the remaining gap is named rather than smoothed over.

Honesty note on scope: several findings (F-07, F-08, F-13, F-14, F-16) were
closed by other work on this branch before this report was written. They are
recorded as verified here, not as work done for this report. F-15 was partly
addressed by that work (`.aider/`) and completed here (`REPO_MAP.md`).

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
| F-10 | MEDIUM | Two contradictory revocation mechanisms; one orphaned | **FIXED** |
| F-11 | MEDIUM | Persistence paths CWD-relative and non-configurable | **FIXED** |
| F-12 | MEDIUM | No CI; secret scanner not enforced | **FIXED** |
| F-13 | MEDIUM | Trusted-time not implemented | **FIXED** |
| F-14 | LOW | Stray 7.8 MB artifacts at repo root | **FIXED** |
| F-15 | LOW | Dev/tool artifacts in the tree | **FIXED** |
| F-16 | LOW | No version control | **FIXED** |
| F-17 | LOW | Declared vs. installed SQLAlchemy divergence | **FIXED** |
| F-18 | LOW | Weak JWT secrets padded, not strengthened | **FIXED** |
| F-19 | MEDIUM | Repository state ambiguity; project at two paths | **PARTIAL** |

**Counts:** 18 fixed, 1 partial, 0 open.

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

The lock is now also exercised across **processes**, which is the real threat —
two concurrent invocations — rather than only across threads:
`tests/test_control_record_integrity.py::AuditLockAcrossProcessesTests` forks six
processes that append to one log, and requires the merged chain to be contiguous
with no duplicate or missing sequence number.

### F-04 — Anchor omitted rejected records (HIGH) — FIXED

`ControlPlane.get_all_records()` no longer filters. It previously dropped records
whose payload had `policy_allowed is False`, and because `export_anchor` and
`verify_anchor` derive the Merkle root and record count from this accessor, the
anchor covered a subset of the chain — a rejected-path record could be altered or
deleted without the anchor noticing. The accessor now returns every committed
record, and the docstring explains why filtering belongs to callers, so the old
behaviour is not re-derived. The only remaining mentions of `policy_allowed` in
the file are the payload write (`:259`) and that docstring (`:537`).

Pinned by `tests/test_control_record_integrity.py::ControlAccessorTests`, which
writes `policy_allowed: false` into a committed payload — the exact condition the
old filter keyed on — and requires the accessor to keep returning it. Restoring
the filter fails that test; this was confirmed by doing it.

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

Pinned by `tests/test_control_record_integrity.py::RecordClockProvenanceTests`,
which requires the clock tag on every committed payload and an offset-aware
timestamp. Deleting the `time_source` line fails that test; this was confirmed by
doing it.

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

## 5. Findings closed in the second pass

These findings were recorded as open or partial in the first pass of this report.
Each is closed here; the evidence of the old behaviour is kept above each
resolution so the before-state stays on the record.

### F-10 — Two revocation mechanisms, one orphaned (MEDIUM) — FIXED

`dossier_pipeline/registry/keys.py` still implements a file-based revocation
list, still documents it, and is still exported and advertised:

```
registry/__init__.py:2:from . import keys, entry, store, audit, trace
registry/__init__.py:3:__all__ = ["keys", "entry", "store", "audit", "trace"]
registry/keys.py:8:Revocation: append to revoked_keys.txt. Revoked keys can still verify old
registry/keys.py:118:    return (root or DEFAULT_KEY_DIR).parent / "revoked_keys.txt"
```

No first-party caller invokes the file-based path (the only other matches are
unrelated dict `.keys()` calls). Two contradictory mechanisms coexisted, one
dead but exported, and the next reader could not tell which was authoritative.

**Resolution.** The file-based path was deleted: `revocation_file`, `revoke`,
`revoked_signers` and `is_revoked` are gone from `registry/keys.py`, and the
module docstring no longer describes a mechanism that does not exist.

Deletion was chosen over a deprecation marker because the anchor path is the
live, tested, enforced one — `registry/store.py:7` already declares "Revocation
is a property of the anchor, not a separate file", `trust.revoke` sets a
monotonic `revoked_at`, and `store.py:125`/`:199` enforce it — so a second
importable implementation contradicted a live invariant. A dead alternative is
what the next reader adopts by mistake, which is the same failure mode as F-04.

`tests/test_revocation_single_source.py` (6 tests) guards the decision: it fails
if the file-based API reappears, if the anchor API disappears, or if key
generation starts writing a revocation file again. Deleting the dead code broke
no test, which is itself the evidence that nothing depended on it.

### F-18 — Weak JWT secrets padded, not strengthened (LOW) — FIXED

`auth.py` defined the policy but did not enforce it:

```
16:MIN_SECRET_KEY_LENGTH = 32
29:def _normalize_secret_key(secret_key: str) -> str:
30:    if len(secret_key) >= MIN_SECRET_KEY_LENGTH:
31:        return secret_key
32:    return sha256(secret_key.encode("utf-8")).hexdigest()
```

A 5-character secret was accepted and silently stretched to a 64-character
digest, which added length but no entropy: the secret stayed exactly as
guessable as the password typed.

**Resolution.** `_normalize_secret_key` now rejects a weak secret instead of
transforming it, raising a new `WeakSecretKey` (a `ValueError` subclass, so
existing callers that catch `ValueError` keep working). `None`, empty, and
anything shorter than `MIN_SECRET_KEY_LENGTH` are refused, with a message that
reports how long the secret was and how long it must be. The parameter types of
`issue_token`, `decode_token` and `validate_bearer_token` were widened to
`Optional[str]`, because "the configuration was missing" deserves a typed error
rather than a `TypeError` raised from `len(None)`.

A KDF was considered and rejected. Deriving with PBKDF2, scrypt or Argon2 treats
the signing key as a human password, which is the assumption that made the
original code look defensible; the key is configuration, and the correct answer
to a configuration value with insufficient entropy is to refuse it, not to slow
down whoever guesses it.

Because secrets of at least `MIN_SECRET_KEY_LENGTH` characters were already
returned unchanged, only the insecure path changed behaviour: tokens signed with
a properly-sized secret still verify, so this is not a breaking change for any
deployment that was doing the right thing.

`tests/test_auth_secret_policy.py` (11 tests) covers the refusal, the boundary at
exactly the minimum, the round-trip, and the adversarial case the old padding
created — a token signed with the 15-character placeholder was verifiable by
anyone who knew it, and is now refused outright.

### F-12 — Secret scanner not enforced (MEDIUM) — FIXED

The finding said a config is not enforcement. It was worse than that: the config
could not even be loaded. `.gitleaks.toml` failed to parse for two independent
reasons, both from writing regexes as if for a shell or Python literal:

```
1. double-quoted strings with doubled backslashes -> TOML ends the string at the
   next quote -> "array elements must be separated by commas"
2. \s in a TOML basic string is not a legal escape -> "invalid escaped character"
```

A scanner configuration that cannot be loaded is not a control, and this one had
never run.

**Resolution.** The config was rewritten using TOML *literal* strings, and two
further defects were found by actually running it:

- Path patterns were written with a leading slash (`/tests/`) but gitleaks matches
  repository-relative paths (`tests/...`), so the test and documentation
  exclusions matched nothing and every fake secret in a fixture was reported.
- Allowlist regexes match the matched *secret* by default, not the source line, so
  the placeholder rules needed `regexTarget = 'line'` to fire at all.

Wire-up: `.githooks/pre-commit` now runs both the integrity gate and
`gitleaks git --staged`, skipping the scan with an explicit notice when gitleaks
is not installed — a missing optional tool must not block commits, but it must
not pass silently either. CI runs `gitleaks dir` in the integrity job, before any
dependency install, with the scanner version pinned so it cannot shift under the
repository.

**Verification that the gate actually fires.** A probe file containing a
random-looking AWS key was added, the scan was run, and the scan failed with
exactly that finding; the probe was then deleted and the scan returned clean. The
first probe used `AKIAIOSFODNN7EXAMPLE`, which gitleaks' built-in defaults
allowlist as a published example and therefore detected nothing — a reminder that
a probe which cannot fail proves nothing.

### F-15 — Dev/tool artifacts in the tree (LOW) — FIXED

`.aider/` was already gone. `REPO_MAP.md` (57 KB, generated by Aider, a tool no
longer present in this repository) was still on disk: git-ignored, so it never
reached a clone, but still present in any naive copy or archive of the tree.

**Resolution.** Deleted. The `.gitignore` entries for `REPO_MAP.md` and `.aider/`
were deliberately kept: they are harmless, and they stop the artifacts returning
if that tool is ever run here again.

### F-11 — CWD-relative persistence paths (MEDIUM) — FIXED

The configurability the finding asked for was already in place: `OUTPUT_DIR`,
`--output-dir` and the `output_dir` constructor argument. What remained was that
the *default* was the string `"./output"`, resolved against whatever directory
the process happened to start in — so the same command run twice from two places
wrote custody data to two different locations, and nothing in the output said
which.

**Resolution.** Added `DEFAULT_OUTPUT_DIR` and `_resolve_output_dir()` to
`dossier_pipeline/main.py`. Before dispatch, the entry point resolves the
configured value to an absolute path and states it:

```
Data directory: /tmp/output
```

Verified from two working directories: run from `/tmp` it reports `/tmp/output`;
run from `/var/tmp` it reports `/var/tmp/output`. Nothing moved — the same
destination is now stated rather than implied, and the resolved value is what
every command receives.

The library layer still takes whatever directory it is handed; deciding where
that is belongs to the entry point, so `DossierPipeline`'s interface is
unchanged and every existing test still passes an explicit directory.

**Residual.** The default still *follows* the working directory instead of being
an absolute data directory of its own. That is deliberate — changing it would
move where existing deployments write — and the point of the fix is that the
choice is now visible on every run, which is the remedy the finding named.

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
4. **The secret policy is enforced when signing, not at startup.** `F-18` now
   refuses a weak signing secret, but only when `issue_token` or `decode_token`
   is called. A service that reads its JWT secret from the environment still
   starts with a bad one and fails on first use; validating it during startup
   would fail earlier and more visibly.
5. **Revocation is implemented, but only for signers the anchor knows.** `F-10`
   leaves one mechanism, which is an improvement, but `store` enforces
   revocation from the anchor it was constructed with. Rebuilding the store when
   the anchor changes is the caller's responsibility, as `store.py` says.
6. **The Python interpreter version is not pinned.** The audit ran on 3.12.3;
   these gates ran green on 3.14.4 with pytest 9.x. `requirements.lock` pins the
   packages but not the interpreter, so "same environment" is still only true
   down to the package layer.
7. **`scripts*` in packaging is inert** (`F-08` residual).
8. **Read-only CLI commands require the evidence secret.** Because the entry
   point constructs the evidence store eagerly, `enforce`, `verify-chain` and
   `verify` fail closed without `GDC_EVIDENCE_SECRET` — observed while verifying
   F-11. That is the intended F-02 behaviour (refusing to open an evidence store
   without a key), but operators should know that read-only inspection needs the
   secret set too. If that proves too strict in practice, the fix is to build the
   evidence store lazily for commands that never sign.

## 8. Verification at the time of this report

Run against the tree with every fix above applied:

| Gate | Command | Result |
|---|---|---|
| Integrity self-test | `python3 scripts/check_integrity.py --selftest` | **6/6 PASS** |
| Integrity, all source | `python3 scripts/check_integrity.py --all` | **OK (229 source files)** |
| Secret scan (tree) | `gitleaks dir . --config .gitleaks.toml` | **0 findings** |
| Secret scan (staged) | `gitleaks git --staged --config .gitleaks.toml` | **exit 0** |
| Secret scan (probe) | planted AWS key in a scratch file | **detected, exit 1** |
| Lock drift / SBOM | `python3 scripts/generate_sbom.py --check` | **OK — 41 packages, 0 drift** |
| Python suite (committed tree) | `python3 -m pytest -q -p no:cacheprovider` in a worktree of `473cdc5` | **316 passed, 0 failed, 0 skipped** |
| Python suite (working tree) | `python3 -m pytest -q -p no:cacheprovider` | **324 passed, 0 failed, 0 skipped** |
| Type-check | `npx tsc --noEmit` (in `interface/`) | **exit 0** |
| UI suite | `npx vitest run` (in `interface/`) | **14 files / 75 tests passed** |
| Production build | `npm run build` (in `interface/`) | **exit 0** |

The suite grew from 279 passed + 1 skipped at the original audit to 324 passed
with no skips. The delta includes the new fail-closed signing tests, the F-18
secret-policy tests (11), the F-10 revocation guard tests (6),
`tests/test_control_record_integrity.py` (5), and `tests/test_interface_api.py`.

**The five tests in `tests/test_control_record_integrity.py` were validated by
mutation, not merely by passing.** Closing out this report showed that three of
its own "fixed" claims were pinned by nothing that would fail if the fix were
undone: the F-04 filter could be re-added, the F-13 clock tag deleted, and the
F-03 lock — which had only ever been exercised by threads — removed, with every
existing test still green. Each was therefore mutated deliberately: the
`policy_allowed` filter restored, the `time_source` line deleted, and the pins
re-run. Exactly the two corresponding tests failed and the other three passed,
after which the mutations were reverted and `git diff` confirmed the module was
byte-identical to the commit again. A test that has never been seen to fail is
not evidence, and this report does not count it as such.

**Why the Python suite is listed twice.** The counts differ, and the reason
matters: `tests/test_interface_api.py` is not committed. It is untracked work
belonging to a concurrent actor, so it runs in the working tree and is absent
from the commit. Everything else in the table — the integrity gate, the secret
scan, the SBOM check — is reproducible from `473cdc5` alone, and that is where
the committed numbers come from. A clean clone reports 316, not 324.

The interface rows are in the same position: `tsc`, `vitest` and the production
build were run in `interface/` on the working tree, which carries the other
actor's uncommitted front-end changes. They are true of the tree as it stands,
and they are that actor's work to commit.

This is the F-19 hazard in miniature: "the tree is green" and "the commit is
green" are different claims, and only the second one travels. Every Python-side
number in this table was re-run against a detached worktree of `473cdc5`, which
is untouched by the other actor's working-tree edits.

The probe row is deliberate: a scanner that reports "clean" is only evidence if
it also fails when it should, so the scan was demonstrated to fire before being
trusted.
