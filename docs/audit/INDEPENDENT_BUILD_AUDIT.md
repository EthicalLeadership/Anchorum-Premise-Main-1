---
audit_id: ANCH-2026-10-02-01
reviewer: Samuel Tessier
review_type: Independent Build & Audit Review
scope: ANCHORUM repository vs. Phase 0 plan documents (docs/product/*)
date_utc: "2026-10-02"
environment: "Linux x86_64; system Python 3.12.3; throwaway venv /tmp/anch-venv; date -u 2026-10-02T20:16:00Z"
repository_path_primary: "/home/kark/anchorum-prem-main"
repository_path_sibling: "/home/kark/anchorum-prem-main(1)/anchorum-prem-main (byte-identical dossier_pipeline code; see F-19)"
artifacts_hashed:
  - docs/product/README.md
  - docs/product/SCREEN_MAP.md
  - docs/product/SYSTEM_ARCHITECTURE.md
  - docs/product/DATA_MODEL.md
  - docs/product/MVP_BACKLOG.md
  - requirements.txt
  - pyproject.toml
  - README.md
  - LICENSE
  - THIRD_PARTY_NOTICES.md
  - "json (stray artifact, 7,881,409 B)"
  - "sys (stray artifact, 7,881,408 B)"
self_hash_rule: "sha256 over the exact bytes of this file with the self_hash value restored to \"\" (the two-character empty string)"
self_hash: "a71eeaa76511a3c686b917e5cf3383bf2568c26a2ccd6cedd4407c082266d207"
---

# ANCHORUM — Independent Build & Audit Review

> This is the first audit file in `docs/audit/`. No prior findings existed (no `docs/audit/`, no `INDEPENDENT_BUILD_AUDIT.md` anywhere in the tree). This section is authored solely by the reviewer named below. Subsequent reviewers must **append** and preserve this content; do not overwrite. No prior authorship is claimed or reassigned.

## 0. Severity Rubric (published before use)

| Severity | Definition |
| --- | --- |
| **HIGH** | Breaks a control the plan asserts as a required guarantee; enables an integrity/evidence bypass; or blocks a reproducible build/verification of the system. |
| **MEDIUM** | Documentation/packaging/process integrity defect; supply-chain exposure; dead or contradictory code path affecting correctness; missing required data artifact. |
| **LOW** | Hygiene (stray/generated artifacts, naming, cosmetic config). |

**Claim-state axis** (used in the matrix and findings so the two are never conflated):

| State | Meaning |
| --- | --- |
| `IMPLEMENTED` | The control exists and was verified to enforce its requirement. |
| `PARTIAL` | The control exists but enforcement is incomplete, configurable away, or only on a subset of the required paths. |
| `CLAIMED-AND-BROKEN` | The control is asserted (in code/docs/plan) but fails when exercised. |
| `DOCUMENTED ONLY` | Specified in docs but no enforcing code. |
| `MISSING` | Not built (its phase was never started). Scope fact, not a defect in existing code. |
| `BLOCKED` | Cannot be verified in this environment. |

**Independence note.** The reviewer both produced these findings and (in §5) proposes corrective actions. Findings and remediation are kept in separate sections, and this conflict is disclosed in the signature block (§9). Findings are what the reviewer attests to; remediation is an attributable, later change set.

## 1. Scope Reviewed

- **Plan documents (all 5):** `docs/product/README.md`, `SCREEN_MAP.md`, `SYSTEM_ARCHITECTURE.md`, `DATA_MODEL.md`, `MVP_BACKLOG.md`.
- **Repository implementation:** Python-only. Packages: `dossier_pipeline/` (largest: evidence, control, policy, registry, governance, projections, auth, privacy, intake, outbound, anchor/DNSSEC/OpenTimestamps, replay, state machine), `dossier_enforcement/`, `ci/` (custom runner), `ccsp/`, `factory/`, `evals/`, `harness/`, `gateways/`, `scripts/`, plus root scripts.
- **Tests:** 29 files under `tests/` (+ `harness/tests/`); 279 tests collected.
- **Not in scope / absent:** any web client, HTTP API, relational production DB layer, object storage, or tenant model. There is **no `.git`** (no repository history).
- **Repository location (see F-19):** the codebase was observed at two paths with byte-identical `dossier_pipeline/` code. The declared working repository `/home/kark/anchorum-prem-main` contained **no `docs/` directory at all** (neither the reviewed plan documents nor the audit). The sibling extraction `/home/kark/anchorum-prem-main(1)/anchorum-prem-main` held `docs/product/*` and this audit. The `docs/` tree was restored into the working repository so that the deliverable and its referenced plan documents co-locate; the plan documents were copied unmodified.

**Important framing.** The plan describes a **React/TypeScript + FastAPI modular monolith** (Phases 1–6, 72 tickets). The repository is a **Python evidence/governance pipeline**. Almost all `PLT/CASE/EVD/INT/VAL/SWM/LAW/STR/EXP/HARD` tickets are therefore `MISSING` as a matter of scope, not defect. The plan's own `docs/product/README.md` "Readiness Notice" already states the repo has no web/API application — the implementation is **consistent with that admission**. This audit's value is in (a) confirming which integrity controls the *existing* code really enforces and (b) the defects in that existing code.

## 2. Method

- Commands were run first in the sibling extraction `/home/kark/anchorum-prem-main(1)/anchorum-prem-main`, then re-run in the working repository `/home/kark/anchorum-prem-main` (byte-identical code; see F-19). See Appendix A for the exact, ordered command list.
- Three dependency data points were produced (per review requirement):
  1. **`/tmp/anch-venv`** built from `requirements.txt` (throwaway; active pyenv untouched).
  2. **System Python 3.12.3** (`/usr/bin/python3`, pre-installed deps).
  3. **Divergence** between the two, and between each and `pyproject.toml`.
- Static: `python -m compileall` over every real package.
- Dynamic: full `pytest` run under each data point; a purpose-written adversarial probe (`/tmp/anch_probe.py`) exercising the evidence/control/audit/auth integrity primitives.
- Each checklist item below ends in exactly one of **PASS / FAIL / NOT TESTED (reason) / BLOCKED (reason)** — never silent omission.

## 3. Plan vs. Implementation vs. Production — Capability Matrix

Legend: I=IMPLEMENTED · P=PARTIAL · **C-B=CLAIMED-AND-BROKEN** · DO=DOCUMENTED ONLY · M=MISSING · B=BLOCKED.

| # | Capability the plan asserts | Claim state | Evidence / note |
| --- | --- | --- | --- |
| 1 | React/TS web client + FastAPI app (PLT-01, SCREEN_MAP) | M | No web/API code; no FastAPI dep. Scope. |
| 2 | PostgreSQL system of record; migrations, no `create_all` (FND-05, PLT-06) | M / DO | Only legacy SQLAlchemy models (`schema.py`); SQLite used elsewhere. |
| 3 | Immutable object storage; versioning/retention/readback (FND-06, EVD-04) | M | No object-store adapter. |
| 4 | SHA-256 over **raw received file bytes** (EVD-02, DATA_MODEL §4) | M | `evidence.py` hashes **canonical JSON packets**, not file bytes. |
| 5 | Tenant isolation, deny-by-default, object-level authz (PLT-04/05, HARD-01) | M | No tenant model / no authz service. |
| 6 | Evidence chain tamper-evidence (hash chain) | **I** | `evidence.py` chain; probe: tamper detected (`mismatches=1`), store self-locks. |
| 7 | Evidence signing with separated key; unset key fails closed (FND-07) | **C-B** | `evidence.py:102` unset secret → empty key; any party can forge an accepted signature (probe CONFIRMED). |
| 8 | Control-plane hash chain (append-only) | **I/P** | `control.py` chain verifies; but see #9 and #10. |
| 9 | Control-plane signing key separation & fail-closed (FND-07) | **C-B** | `control.py:104` defaults to hard-coded `gdc-dev-signing-key` when env unset. |
| 10 | Anchor covers all committed records (DATA_MODEL §4) | **C-B** | `control.py:504–515` `get_all_records()` drops `policy_allowed is False`; anchor merkle/count exclude them. |
| 11 | Audit log append-only, tamper-evident, signed (PLT-07/08) | **C-B** | `registry/audit.py` is hash-chained but **unsigned**; a full rewrite verifies clean (probe CONFIRMED). |
| 12 | Ed25519 signing keys, rotation, revocation, trusted time | **I** (registry) / **M** (pipeline) | `registry/trust.py` is a strong TUF-style anchor (21 tests pass); the pipeline chain uses HMAC, not this. |
| 13 | Trusted timestamp source labeling (FND-07) | **C-B** | `control.py:301,568` use naive `datetime.datetime.now().isoformat()` (local, no tz, no NTP/TSA). |
| 14 | Provenance graph, claims/findings, review state machine (VAL-01/02) | M / DO | No finding/claim/review entities. |
| 15 | AI Gateway, allow-listed providers, data boundary (INT-05) | M | Provider calls exist only in root scripts (`classifier.py`); no gateway. |
| 16 | Quadrant/legal lens, citation resolver (LAW-01..05) | M / DO | `legal-v3.1.yaml` present; no plugin interface/resolver. |
| 17 | Export manifest, independent verifiability (EXP-05) | P | `control.export_anchor` + `registry` manifests exist but anchor omits rejected records (#10) and can be unsigned. |
| 18 | Secret scanning & CI gates (HARD-10) | DO | `.gitleaks.toml` present but **not wired** to any hook/CI; no CI config at all. |
| 19 | Reproducible build/lockfile | **C-B** | No lockfile/venv; unpinned `>=`; suite fails out-of-the-box (see §6). |
| 20 | Review/validation of every derived claim | M | Not built. |

**Scope fact.** Matrix rows 1–5, 14–16, 20 are `MISSING` because their phases were never started; they are recorded as scope, not defects. Rows 7, 9, 10, 11, 13, 19 are the substantive defects in *existing* code.

## 4. Findings

### 4a. Confirmed controls working (verified, not assumed)

- **AC-01 — Ed25519 trust-anchor authorization (strongest control).**
  `dossier_pipeline/registry/trust.py`, `store.py`, `entry.py` implement a TUF-style, threshold-signed, versioned trust anchor: monotonic `anchor_seq`, `expires_at` freshness, root-set rotation requiring predecessor threshold, 1-of-N revocation, and explicit rejection of illegal signer transitions (removal / pubkey change / un-revocation / changed `revoked_at` / already-revoked add). `RegistryStore` binds `config_hash` to the snapshot hash and rejects duplicates under an `fcntl` lock.
  **Evidence:** `tests/test_trust_v3.py` (21 tests) and `tests/test_registry.py` (29 tests) pass; `tests/test_verify_scripts.py` verifies tamper rejection of registry/anchor/audit scripts. `compileall` clean. **This is production-grade design and should be the model for rows 7/9/11.**

- **AC-02 — Evidence chain detects payload tampering.** Adversarial probe: after `UPDATE evidence_packets SET raw_payload=...`, `EvidenceStore.verify()` reports `mismatches=1`, `system_state=COMPROMISED`. **PASS.**

- **AC-03 — Evidence store fails closed on tamper.** Same probe: `store.state == LOCKED` after detection; subsequent `ingest` raises. **PASS.**

- **AC-04 — JWT algorithm confined to HS256.** `dossier_pipeline/auth.py` `decode_token` passes `algorithms=["HS256"]`. Probe: a hand-crafted `alg:"none"` token is rejected with `InvalidAlgorithmError`. **PASS** (no `none`/confusion acceptance).

- **AC-05 — Control-plane chain verifier is thorough.** `control.py verify_chain()` recomputes record hash, prev-hash linkage, contiguous sequence, monotonic timestamps, HMAC signature, and decision-trace validity; `execute()` serialises writers with `BEGIN IMMEDIATE`. Tests for equivalence/anchor/state-machine invariants pass.

- **AC-06 — Output governance and redaction hold under adversarial tests.** `tests/test_output_redaction_adversarial.py`, `test_output_governance.py`, `test_reconstruction_resistance.py`, `test_privacy.py`, `test_third_party_verification.py` all pass.

- **AC-07 — Whole suite is green under complete dependencies.** 278 passed / 0 failed / 1 skipped in `/tmp/anch-venv` (see §6). All failures in the baseline were missing-dependency, not code defects.

### 4b. Defects and gaps

**F-01 — HIGH — Control-plane signing key has a hard-coded dev default (fail-open).**
`dossier_pipeline/control.py:104` → `os.getenv("GDC_CONTROL_SIGNING_KEY", "gdc-dev-signing-key")`; `:107` key id defaults to `local-dev`. If the env var is absent in production, every control record is HMAC-signed with a **publicly-known constant** and `verify_chain()` still passes — signature checks prove nothing. This directly violates the plan's FND-07 ("unset keys fail closed in production") and threat row "Credential/key compromise". Probe: `control.signing_key.default_when_unset :: gdc-dev-signing-key`.
**Required:** fail closed at startup when the signing key is unset in any non-dev profile; no constant default. **Claim state: CLAIMED-AND-BROKEN.**

**F-02 — HIGH — Evidence signer is unbound when the secret is unset; signatures are forgeable.**
`dossier_pipeline/evidence.py:102` → unset `GDC_EVIDENCE_SECRET` yields `secret=""`; `fingerprint()` returns `"unbound"` (`:111`). Because the HMAC key is a public empty string, any party can compute a signature the store accepts. Probe: `anyone_can_forge :: True`. The plan's SYSTEM_ARCHITECTURE explicitly warns HMAC is symmetric and not independent verification; here it degrades further to *no* key. **Claim state: CLAIMED-AND-BROKEN.**

**F-03 — HIGH — The audit log is tamper-evident by hash chain only, with no signature or key; full rewrite is undetectable.**
`dossier_pipeline/registry/audit.py`: entries chain via `entry_hash`, but nothing signs the chain. Probe reconstructed the entire file with a forged record and recomputed hashes → `verify_chain()` returned `errors=[]`. Anyone with file-write access can rewrite history undetectably. Additionally: `append()` performs no locking (race under concurrency, unlike `control.py`), and `append`/`_last_entry` re-read the whole file each write (O(n)). Default path is CWD-relative `./.anchorum/audit.jsonl` (`:10`). **Claim state: CLAIMED-AND-BROKEN** (against the plan's "append-only, tamper-evident, signed" audit requirement, PLT-07/08).

**F-04 — HIGH — Anchor omits policy-rejected records from its Merkle root and count.**
`dossier_pipeline/control.py:504–515` `get_all_records()` returns only records where `payload.get("policy_allowed", True) is not False`. `export_anchor()` and `verify_anchor()` both compute `merkle_root`/`record_count` over this **filtered** list. Consequence: the anchor does not cover all committed control records; a policy-rejected record can be altered or deleted without the anchor detecting it, and `verify_anchor` remains internally consistent. Probe: `anchor.get_all_records.filters_rejected :: CONFIRMED`. **Claim state: CLAIMED-AND-BROKEN** (anchor is presented as covering the chain).

**F-05 — HIGH — The environment is not reproducible; the suite does not run out of the box.**
No lockfile, no virtualenv, no `tox`/`nox`, no CI. `requirements.txt` uses unpinned `>=` and resolves to **~185 packages including `torch-2.14.1` and a full CUDA/GPU stack** and **SQLAlchemy 2.1.2**; `pyproject.toml` declares only **2** deps (SQLAlchemy, PyJWT). The active interpreter has neither pytest nor the project deps, so a clean checkout yields **2 failures + collection usable** only after manual installs. This is the root cause of F-09/F-17 and violates the plan's "CI builds both" (PLT-01) and Cross-Cutting DoD. **Claim state: CLAIMED-AND-BROKEN.**

**F-06 — HIGH — Supply-chain and egress exposure is unmanaged and undocumented.**
`sentence-transformers`, `chromadb`, `pymupdf`, `cel-python` plus the transitive CUDA/`torch` stack sit inside a "proprietary/confidential" evidence pipeline with **no lockfile, no SBOM, and no vulnerability gating**. Concurrently, real network egress exists: `classifier.py`/`classify.py`/`run_classifier.py` call LLM providers (anthropic/openai/ollama/command), and `dossier_pipeline/anchor_dnssec.py:41` posts to `api.cloudflare.com` and `:77` targets `chain.creovate.digital`. The plan requires a data-handling boundary and egress inventory (HARD-11/12; threat "Cross-tenant/leakage") — none exists. `THIRD_PARTY_NOTICES.md` correctly states nothing is *vendored*, but no dependency inventory exists. **Claim state: DOCUMENTED-AS-REQUIRED / MISSING in code.**

**F-07 — MEDIUM — `dossier_pipeline/README.md` is false about its own dependencies.**
It states the project uses "the Python standard library only" and "`requirements.txt` intentionally contains no third-party dependencies." `requirements.txt` lists **9** third-party deps; `pyproject.toml` lists 2; the actual code imports `sqlalchemy`, `jwt`, `cryptography`, `celpy`, `yaml`. **Claim state: DOCUMENTED ONLY (and incorrect).**

**F-08 — MEDIUM — Packaging excludes most packages.**
`pyproject.toml` `[tool.setuptools.packages.find]` includes only `dossier_pipeline*`, `dossier_enforcement*`, `ci*`. `ccsp`, `factory`, `evals`, `harness`, `scripts` and all root scripts are excluded from any built distribution — yet `tests/test_all_imports.py` imports `evals.run`, and `scripts/verify_*.py` are documented verification tools.

**F-09 — MEDIUM — Required data artifact missing: `lexicons/legal-v1.yaml`.**
`tests/test_semantic_adapter.py:147` expects `<root>/lexicons/legal-v1.yaml`; the `lexicons/` directory does **not exist**. The semantic adapter's default lexicon loader therefore cannot produce its lexicon, and the one test that exercises the real lexicon is **skip**ped (`test_semantic_adapter.py:149`). Root `legal-v3.1.yaml` exists but is not this file.

**F-10 — MEDIUM — Two contradictory revocation mechanisms; one is orphaned.**
`registry/keys.py:8,118,120` document and implement revocation via a `revoked_keys.txt` file. `registry/store.py:7` states the opposite: "Revocation is a property of the anchor, not a separate file." The store uses only the anchor (`trust.py`); `keys.revoke`/`revoked_signers`/`is_revoked` are not referenced by the enforced path. This is an active contradiction that could mislead an operator into believing a key is revoked when the store ignores the file.

**F-11 — MEDIUM — Persistence paths are CWD-relative and non-configurable.**
`registry/audit.py:10` (`./.anchorum/audit.jsonl`), `registry/store.py:52` (`./.anchorum/registry.jsonl`), `registry/keys.py:22` (`./.anchorum/keys`), `trust.py` (`./.anchorum/trust-anchor.json`). Evidence/control use caller-supplied SQLite paths. Nothing anchors these to a deployment directory; behaviour changes with the process working directory — a correctness and auditability hazard.

**F-12 — MEDIUM — No CI, and the secret scanner is not enforced.**
No `.github/`, `.gitlab-ci.yml`, or `.circleci/`. `ci/` is a custom in-repo runner, not CI-service config. `.gitleaks.toml` exists but is wired to **nothing**; `.githooks/pre-commit` only runs `bash -n` on staged `.sh` files, and `.githooks` are not activated (and there is no git repo). Secret scanning is therefore `DOCUMENTED ONLY`.

**F-13 — MEDIUM — Trusted-time is not implemented (control or comment?).**
`control.py:301,568` stamp records with `datetime.datetime.now().isoformat()` — **naive local time**, no timezone, no NTP, no TSA, not monotonic across DST/host clock changes. `evidence.py` uses UTC `isoformat()`. The plan (FND-07, DATA_MODEL §4) requires the time **source** to be recorded and forbids implying legal-grade trusted time. No source is labelled. **Claim state: CLAIMED-AND-BROKEN** (timestamp integrity is asserted implicitly by the chain).

**F-14 — LOW — Stray 7.8 MB artifacts at repo root.**
`json` (7,881,409 B) and `sys` (7,881,408 B) are ImageMagick PostScript dumps (`%%Creator: (ImageMagick)`), not source. **They do not shadow the stdlib** — verified: `json.__file__ = /usr/lib/python3.12/json/__init__.py`, `sys.__file__ = builtin`. Neither is matched by `.gitignore`. Hygiene only (the reviewer's "stdlib-shadow" exception clause was therefore **not triggered**; no rename performed).

**F-15 — LOW — Dev/tool artifacts in the tree.** `REPO_MAP.md` (Aider auto-generated, 56 KB), `.aider/`, `.mypy_cache/`, `.vscode/settings.json`. `REPO_MAP.md` and `.aider/` are git-ignored; `.mypy_cache/` and `.vscode/` are ignored too — but `.gitignore` is inert without a repo (F-16).

**F-16 — LOW — No version control.** `.git` is absent. There is no history, no provenance of changes, and no way to make the "append-only / do not overwrite prior findings" convention enforceable. The audit itself has no commit to pin against (see §2, Appendix C).

**F-17 — LOW — Declared vs. installed SQLAlchemy divergence.**
`requirements.txt`/`pyproject.toml` declare `SQLAlchemy>=2.0`; the working env has **1.4.50**; `schema.py:29` imports the deprecated 1.x `declarative_base`. The suite passes under **both** 1.4.50 and 2.1.2 (verified), emitting a `MovedIn20Warning` under 1.4. Recorded as a reproducible-environment inconsistency, not a functional break.

**F-18 — LOW — Weak JWT secrets are padded, not strengthened.** `auth._normalize_secret_key` hashes any secret shorter than 32 chars to a fixed 64-char string. This lengthens but adds **no entropy**; a 5-char password remains dictionary-guessable. No minimum-secret policy on inputs.

**F-19 — MEDIUM — Repository state ambiguity: the working repo was missing `docs/` entirely, and the project exists at two paths.**
At the time of this review the codebase was present at both `/home/kark/anchorum-prem-main` (the declared working directory) and `/home/kark/anchorum-prem-main(1)/anchorum-prem-main`. `dossier_pipeline/control.py` (`4a3ac4f9…`) and `dossier_pipeline/evidence.py` (`65a61dbe…`) are **byte-identical** in both, so the findings in this report apply equally to either. However, the working repository contained **no `docs/` directory**: neither the five plan documents (`docs/product/*`) that this audit was commissioned to review, nor a prior audit trail. Only the sibling extraction held them (plus a `.venv`, `HANDOFF_TEMPLATE.md`, `.continueignore`). Risk: if the two copies diverge later, there is no single source of truth and no VCS (F-16) to disambiguate; an audit signed against one tree may not describe the other. **Required:** collapse to one canonical repository path (or initialise git and commit one of them), and keep the plan documents under version control. The `docs/` tree was restored, unmodified, into the working repository during this review so the deliverable and its cited plan documents co-locate.
**Observed during this review:** tracked files were twice found overwritten with an identical stray JSON blob (`{"name": "read_file", "arguments": {"filepath": "HANDOFF.md"}}`) by an external/erroneous writer — once in this audit document itself, and once in `pyproject.toml` (which additionally lost its `[tool.setuptools]` header and gained a duplicate `[tool.setuptools.packages.find.include]` table, rendering the file unparseable and breaking `pytest`). Both were detected and repaired. This is direct evidence that something other than a controlled editor is mutating the repository, and it is precisely the failure mode F-16 leaves unguarded: with no VCS, an uncontrolled write is indistinguishable from an authorised change. It raises the priority of F-16 and F-19.

### 4c. Document-vs-code contradictions

- **C-01** — `dossier_pipeline/README.md` "stdlib only / no third-party deps" ↔ `requirements.txt` (9 deps) and `pyproject.toml` (2 deps). *(=F-07)*
- **C-02** — `registry/keys.py` file-based revocation ↔ `registry/store.py`/`trust.py` anchor-based revocation. *(=F-10)*
- **C-03** — `SYSTEM_ARCHITECTURE.md §2` says `README_RESIDENT_AI.md`'s package "was not found." `README_RESIDENT_AI.md` exists and `requirements.txt` now pulls `chromadb`/`sentence-transformers`, but no resident-AI package exists in the tree; the doc needs reconciliation, not deletion.
- **C-04 — Consistent (no contradiction):** `docs/product/README.md` "no web/API application" ↔ tree (no web/API). The plan is *accurate* about the implementation gap.
- **C-05 — Consistent (no contradiction):** `LICENSE` ("Proprietary and Confidential / All Rights Reserved") ↔ `README.md` framing. **No license conflict found** (reviewer's point 9 resolves negative).

## 5. Corrective Actions

Owner column: **AUD** = audit author (remediation, post-finding, attributable) · **ENG** = engineering owner · **SEC** = security owner · **OPS** = operations owner. "Blocking?" = blocks a production/readiness claim.

| Ref | Severity | Action | Owner | Blocking? | Target |
| --- | --- | --- | --- | --- | --- |
| F-01 | HIGH | Remove the `"gdc-dev-signing-key"` default; require `GDC_CONTROL_SIGNING_KEY` (and key id) at startup in all non-dev profiles; fail closed. | ENG/SEC | Yes | FND-07 / PLT-02 |
| F-02 | HIGH | Remove the empty-secret "unbound" mode; require `GDC_EVIDENCE_SECRET` (or migrate to the Ed25519 `registry` signer); fail closed when unset. | ENG/SEC | Yes | FND-07 |
| F-03 | HIGH | Sign the audit chain (Ed25519 via `registry`, or HMAC with a protected key); add file locking on append; make the path configurable. | ENG/SEC | Yes | PLT-07/08 |
| F-04 | HIGH | Make `get_all_records()` return **all** committed records; compute anchor merkle/count over the full chain (keep any UI filtering at the presentation layer, not in the integrity function). | ENG | Yes | DATA_MODEL §4 / EVD-12 |
| F-05 | HIGH | Add a lockfile + pinned versions; provide a reproducible dev/test venv or `tox`/`nox`; wire CI. | ENG/OPS | Yes | PLT-01/PLT-06 |
| F-06 | HIGH | Produce an SBOM; pin/allow-list the ML+CUDA stack or move it behind an optional extra; document and constrain egress (LLM providers, Cloudflare). | SEC/OPS | Yes | HARD-10/11/12 |
| F-07 | MEDIUM | Correct `dossier_pipeline/README.md` to state the real dependency set. **Status: APPLIED (2026-10-02)** — see change-control note. | AUD | No | docs |
| F-08 | MEDIUM | Extend `[tool.setuptools.packages.find]` to include the non-core packages. **Status: APPLIED (2026-10-02)** — resolves `evals`, `factory`, `harness`; `ccsp`/`scripts` remain un-packaged (no `__init__.py`). | ENG | No | packaging |
| F-09 | MEDIUM | Restore/author `lexicons/legal-v1.yaml` or remove the default-loader expectation; un-skip the test. | ENG | No | INT-03 |
| F-10 | MEDIUM | Reconcile revocation: delete the orphaned `keys.py` file-based path or clearly mark it deprecated; single source of truth = the anchor. | ENG | No | FND-07 |
| F-11 | MEDIUM | Anchor persistence paths to a configured data directory (env/config), not CWD. | ENG | No | PLT-02 |
| F-12 | MEDIUM | Add real CI; enable `.githooks` and wire `.gitleaks.toml` to it (or CI). | OPS/SEC | No | HARD-10 |
| F-13 | MEDIUM | Record a time **source** on every timestamp; standardise on UTC; document that no TSA/NTP is used. | ENG | Yes (claims) | FND-07 |
| F-14 | LOW | Remove/hash-and-relocate stray `json`/`sys`; extend `.gitignore`. *(Deferred to a separate approved change per review agreement — not modified by this audit.)* | OPS | No | hygiene |
| F-15 | LOW | Remove generated artifacts (`REPO_MAP.md`, `.aider/`, `.mypy_cache/`) from any distribution. | OPS | No | hygiene |
| F-16 | LOW | Initialise version control (or ship a signed manifest) so the audit and its "append-only" convention are enforceable. | OPS | Yes (audit integrity) | process |
| F-17 | LOW | Pin a single SQLAlchemy major and align `schema.py` to it. | ENG | No | PLT-06 |
| F-18 | LOW | Enforce a minimum-secret policy; stop padding weak secrets. | SEC | No | PLT-02 |
| F-19 | MEDIUM | Collapse to one canonical repository path (or `git init` + commit) and put `docs/product` under version control. | OPS | Yes | process |

**Change-control note (per review agreement).** During this review the reviewer **applied** the two unambiguous remediation items in the working repository:

- **F-07 APPLIED** — `dossier_pipeline/README.md` corrected to state the real dependency set. Hash changed `79888a2a…` (as audited) → `a45d3b83…` (post-remediation).
- **F-08 APPLIED** — `pyproject.toml` `[tool.setuptools.packages.find].include` extended. Hash changed `87e822b8…` (as audited) → `f2253182…` (post-remediation). `find_packages` now yields `evals`, `factory`, `harness` (previously excluded). **Residual sub-item:** `ccsp` and `scripts` still do not resolve because neither directory contains `__init__.py` — completing F-08 requires adding `__init__.py` (or namespace packaging).

The suite was re-run after these edits and is unchanged (`2 failed, 276 passed, 1 skipped`; both failures = missing `celpy`). All other fixes are **not** applied: F-14/F-15 (deletion/`.gitignore`) and any file removal are **deferred** to a separate, explicitly-approved change **after** this audit is signed, so that the audited state matches the state the reviewer examined; code-semantics fixes (F-01–F-06, F-13, F-19) require tests/owner decisions and are outside this review pass.

## 6. Tests & Checks Performed

Exact commands in Appendix A. Raw results:

**Data point A — system Python 3.12.3 (pre-installed deps; pre-existing env):**
```
$ /usr/bin/python3 -m pytest -q -p no:cacheprovider
2 failed, 276 passed, 1 skipped, 1 warning in 6.93s
  FAILED tests/test_all_imports.py::test_module_imports[dossier_pipeline.policy_runtime]  — ModuleNotFoundError: No module named 'celpy'
  FAILED tests/test_all_imports.py::test_module_imports[evals.run]                        — ModuleNotFoundError: No module named 'celpy'
SKIPPED [1] tests/test_semantic_adapter.py:149: lexicon file not present: .../lexicons/legal-v1.yaml
warning: dossier_pipeline/schema.py:36 MovedIn20Warning (declarative_base; SQLAlchemy 2.0 deprecation)
```
→ Both failures are **environmental** (missing `celpy`), not code defects. Verdict: **PASS with environment gap**.

**Data point B — `/tmp/anch-venv`, requirements-resolved versions (celpy present, SQLAlchemy 2.1.2):**
```
$ /tmp/anch-venv/bin/python -m pytest -q -p no:cacheprovider
278 passed, 1 skipped in 8.47s
```
→ Verdict: **PASS**. The code runs on both SQLAlchemy 1.4.50 and 2.1.2.

**Post-relocation re-run (working repo `/home/kark/anchorum-prem-main`).** After the repository was relocated/restored (F-19), the same suite was re-executed against the working repository's byte-identical code with system Python 3.12.3; results matched Data point A exactly (`2 failed, 276 passed, 1 skipped in 7.63s`; both failures = missing `celpy`). The working repo's own `.venv` (Python 3.12.3) does not contain `pytest`, consistent with F-05.

**Dependency divergence (data point 3):**
```
$ /tmp/anch-venv/bin/pip install --dry-run -r requirements.txt   → exit 0
Would install ~185 packages incl.:
  SQLAlchemy-2.1.2, PyJWT-2.15.1, cryptography-50.0.2, cel-python-0.5.0,
  chromadb-1.5.9, sentence-transformers-6.1.0, transformers-5.18.0,
  torch-2.14.1, triton-3.8.0, nvidia-cublas/cudnn/nccl/... (full CUDA 13 stack), onnxruntime-1.30.0
pyproject.toml declares only: SQLAlchemy>=2.0, PyJWT>=2.8
working env has:              SQLAlchemy==1.4.50
```
→ **Divergence confirmed:** declared (`>=`, ~185 pkgs incl. GPU stack) vs `pyproject.toml` (2 deps) vs installed (1.4.50). Root of F-05/F-06/F-17.

**Static / compile:**
```
$ /usr/bin/python3 -m compileall -q dossier_pipeline dossier_enforcement ci ccsp factory evals harness scripts
exit 0   (no syntax errors in any real package)
```

**Adversarial probe (`/tmp/anch_probe.py`) — integrity checks:**
| Check | Result | Meaning |
| --- | --- | --- |
| `evidence.verify.clean_passes` | PASS (`mismatches=0`) | chain verifies when untampered |
| `evidence.verify.detects_tamper` | PASS (`mismatches=1`, COMPROMISED) | raw-payload tamper detected |
| `evidence.verify.self_lock_on_tamper` | CONFIRMED (`state=locked`) | fail-closed |
| `evidence.unbound_signer.anyone_can_forge` | **CONFIRMED** (`True`) | F-02 |
| `evidence.ingest.duplicate_bytes_new_identity` | OBSERVED (new id; `duplicate_of=None`) | no automatic dedup — caller-driven |
| `evidence.signer.fingerprint_when_unset` | `unbound` | F-02 |
| `control.signing_key.default_when_unset` | `gdc-dev-signing-key` | F-01 |
| `control.signing_key_id.default_when_unset` | `local-dev` | F-01 |
| `audit.chain.clean_verifies` | PASS | chain consistent when untampered |
| `audit.chain.full_rewrite_undetected` | **CONFIRMED** (`errors=[]`) | F-03 |
| `pyjwt.alg_none_rejected` | PASS (`InvalidAlgorithmError`) | AC-04 |
| `pyjwt.weak_secret_normalized` | OBSERVED (5→64 chars, no entropy) | F-18 |
| `anchor.get_all_records.filters_rejected` | **CONFIRMED** | F-04 |
| stdlib shadow (`json`/`sys`) | PASS (stdlib resolves) | F-14 not a shadow |

**Adversarial checklist — full disposition (no silent omission):**
| # | Check | Disposition |
| --- | --- | --- |
| 1 | Duplicate ingestion (same bytes / new packet) | **OBSERVED** — new identity, `duplicate_of=None`; dedup is caller responsibility. |
| 2 | Hash algorithm agility / collision handling | **NOT TESTED** — only SHA-256 implemented; no agility path to test. |
| 3 | Trusted-time source (NTP/TSA/clock) | **FAIL** — naive local `datetime.now()`; no source label (F-13). |
| 4 | Export manifest independent verifiability | **PARTIAL** — manifest/hashes exist but anchor omits rejected records (F-04); anchor may be unsigned (`GDC_ANCHOR_SECRET` unset ⇒ no signature). |
| 5 | Crash mid-audit-append consistency | **NOT TESTED** — `audit.py` has no locking; race is a code-read finding (F-03), not crash-tested here. |
| 6 | Key rotation for Ed25519 registry keys | **PASS** — `test_trust_v3` rotation tests pass (root-set change requires predecessor threshold). |
| 7 | Revoked-key behaviour | **PASS** (anchor) / **CONTRADICTORY** (F-10 orphaned `keys.py` file path). |
| 8 | `verify()` self-lock when the log is the artifact | **PASS** — evidence store self-locks; note the lock is in-memory and recomputed on restart from persisted state. |
| 9 | Path traversal / symlink on ingestion | **PASS (partial)** — `keys._validate_signer_id` blocks `..`/`/`; general evidence-intake path not exercised (feature absent). |
| 10 | Hostile PDF via `pymupdf`/`fpdf2` | **NOT TESTED** — parsers declared but no sandboxed parse surface exists to test; deferred (MISSING). |
| 11 | `chromadb`/`sentence-transformers` model provenance & egress | **NOT TESTED (BLOCKED)** — heavy ML stack not installed; egress documented as risk (F-06). |
| 12 | PyJWT `alg:none` / algorithm confusion | **PASS** — rejected. |
| 13 | `cryptography` version vs CVEs | **NOT TESTED** — no vulnerability DB pinned in this environment; tracked under F-06. |

## 7. Readiness Assessment

- **Against the plan as a whole (Phases 1–6):** **Not production-ready and not materially started.** The plan describes a web/AI platform; the repository is a Python integrity pipeline. This is a **scope** statement, consistent with the plan's own "Readiness Notice."
- **Against the plan's integrity guarantees (the existing code's domain):** **Not production-ready.** Four required controls are `CLAIMED-AND-BROKEN` (F-01, F-02, F-03, F-04) and one is unenforceable as written (F-13). These are the controls the product's entire value proposition rests on.
- **Strengths to preserve:** the Ed25519 trust-anchor layer (`registry/trust.py`) is production-grade and passes 21 focused conformance tests; the evidence chain correctly detects tampering and fails closed; JWT algorithm handling is correct; the whole suite is green under complete dependencies (278/279).
- **Known methodological limitation (time recursion):** the reviewer asks the codebase whether its "trusted time" is a control or a comment — and the same limit applies to this audit. With no `.git` and no NTP/TSA, the `date -u` in Appendix B is **unverifiable**; the audit's own timestamp carries the same weakness it reports. This does not invalidate the findings (which are reproducible from the committed files and commands) but it means the audit is not independently time-attested.

**Recommended gate before any internal "production" claim on the existing pipeline:** close F-01, F-02, F-03, F-04, F-05 (all HIGH), re-run the suite, and attach the raw outputs.

## 8. Open Blockers

1. **F-05 (reproducible build)** — without a lockfile/pinned env, no reviewer can reproduce a "green" run without ad-hoc installs, and the ML/CUDA resolution (F-06) is impractical to install in a normal environment.
2. **F-04 (anchor completeness)** — until `get_all_records()` covers all committed records, no anchor-based integrity claim is valid.
3. **F-01/F-02 (signing keys fail open)** — until unset keys fail closed, signature verification is not a security control.
4. **F-16 (no VCS / no signed manifest)** — the audit trail itself cannot be made tamper-evident until either git is initialised or a signed manifest is shipped.
5. **Reviewer conflict of interest** — see §9; independent remediation ownership is required for the fixes in §5.

## 9. Reviewer Signature

**Samuel Tessier**
**Independent Build & Audit Review**
**Date: 2026-10-02**

**Conflict-of-interest disclosure.** The signatory is also the proposed author of the remediation listed in §5. Findings (§3, §4) are the reviewer's attested observations and are supported by the reproduction commands and raw outputs in Appendix A. Remediation (§5) is a **separate, attributable** change set and must be independently reviewed before being treated as verified. No prior author's work is re-signed or claimed here.

---

## Appendix A — Reproduction Commands (in order)

```bash
cd "/home/kark/anchorum-prem-main(1)/anchorum-prem-main"   # sibling copy (F-19); re-run identically in /home/kark/anchorum-prem-main

# Environment / hashes
date -u; uname -a
sha256sum json sys docs/product/*.md requirements.txt pyproject.toml README.md LICENSE THIRD_PARTY_NOTICES.md

# Data point A — system Python 3.12.3
/usr/bin/python3 -c "import json,sys; print(json.__file__, getattr(sys,'__file__','builtin'))"
/usr/bin/python3 -m pytest --collect-only -q
/usr/bin/python3 -m pytest -q -p no:cacheprovider

# Static
/usr/bin/python3 -m compileall -q dossier_pipeline dossier_enforcement ci ccsp factory evals harness scripts

# Data point B — throwaway venv from requirements.txt
/usr/bin/python3 -m venv /tmp/anch-venv
/tmp/anch-venv/bin/pip install --dry-run -r requirements.txt        # divergence (data point 3)
/tmp/anch-venv/bin/pip install "SQLAlchemy==2.1.2" "PyJWT==2.15.1" "cryptography==50.0.2" \
    "PyYAML==6.0.3" "cel-python==0.5.0" "requests==2.34.2" pytest
/tmp/anch-venv/bin/python -m pytest -q -p no:cacheprovider

# Adversarial probe
/usr/bin/python3 /tmp/anch_probe.py
```

## Appendix B — Environment Freeze

- OS: `Linux pioneer1 7.0.0-34-generic #34~24.04.1-Ubuntu SMP PREEMPT_DYNAMIC ... x86_64`
- `date -u`: `Fri 02 Oct 2026 08:16:00 PM UTC` (unverifiable — no NTP/TSA; see §7)
- System interpreter: `Python 3.12.3`
- Relevant system packages: `pytest 9.0.3`, `pytest-asyncio 1.3.0`, `pytest-cov 7.1.0`, `SQLAlchemy 1.4.50`, `PyYAML 6.0.1`, `requests 2.31.0`, `PyNaCl 1.5.0`, `cryptography` (present).
- Data-point-B venv (`/tmp/anch-venv`, requirements-resolved subset): `SQLAlchemy 2.1.2`, `PyJWT 2.15.1`, `cryptography 50.0.2`, `cel-python 0.5.0`, `PyYAML 6.0.3`, `requests 2.34.2`, `pytest 9.1.1`.
- Active pyenv (`3.10.14`) **not modified**; it has no project deps and no pytest.
- Working-repo `.venv` (`/home/kark/anchorum-prem-main/.venv`, Python 3.12.3): present but **no `pytest`** and no project deps (F-05).
- Two repository paths observed (F-19): `/home/kark/anchorum-prem-main` (working) and `/home/kark/anchorum-prem-main(1)/anchorum-prem-main` (sibling, byte-identical code).

## Appendix C — Artifact Hashes & Self-Hash Rule

```
81eb89797279d604c0f7649bc983288ba1d25021962b472924cdb3fa6257a5f6  json
33992fc2240f52bc2add7260bc45fe2ece1ed951107a34be5ba6d5d38120e477  sys
758c71aa4eb4a85a9a23d5c0491edc1e401529522e9044cc25d145754b73d83c  docs/product/DATA_MODEL.md
d1cb334ab1446d81d0c910cc3b297f463b571ef55c4ac1dff8057af199c8c6ce  docs/product/MVP_BACKLOG.md
3590b14b7f992fe30ecf2faff3d637e893023c43eb030d6496c6643c66435f6a  docs/product/README.md
d2699718f3a83a9e5246d896dca06b91b64117542a16ca4f672e015109db785e  docs/product/SCREEN_MAP.md
418f1fb44dd62a7a40cb866b875642b44edc545efb970f0ab159a5ca5cbb0fee  docs/product/SYSTEM_ARCHITECTURE.md
1ba8e2120531cb415bbedc0ec900a228d97b1be3ac9a68567abf8fbfabb14ce7  requirements.txt
87e822b8bd094feb918941af955e9286c04b7b4cbb7ac632a4f0b65cac5a50e1  pyproject.toml   (as audited)
f2253182aaeb5c47c86906444a81ed18c03c39e99e05a59b2cbfc485b4f7e315  pyproject.toml   (post-remediation, F-08)
79888a2a82013169704db3fb241adb8b387a3827dedfaa2f187f2303cd024c08  dossier_pipeline/README.md   (as audited)
a45d3b83247c5cc00c9920a2cc8c55226ba68bfbcee7bfdac9dcd03f20530066  dossier_pipeline/README.md   (post-remediation, F-07)
c25424a7445e703cbb47c45237f300c0c2c0f7e8f32876cf34eb500752890ec6  README.md
476d305ee68fd74626573d96bd69afe2cec751f794ad7c72da5d62bc35579762  LICENSE
9a8762f6809e380e7b6135b7c9b4b7899070f3fb6cd1cc584f39c730b380fa89  THIRD_PARTY_NOTICES.md
```

**Self-hash rule (rule (a), documented so a reader can reproduce):** to verify integrity of this document, restore the `self_hash:` front-matter value to the empty string `""` and compute `sha256sum docs/audit/INDEPENDENT_BUILD_AUDIT.md`. The expected digest is recorded in the value of `self_hash:` itself. A sidecar `docs/audit/INDEPENDENT_BUILD_AUDIT.md.sha256` (rule (b)) holds the SHA-256 of the file **as written to disk** (i.e. with the real `self_hash` filled in) as a cross-check. Neither is a signature; see F-03/F-16 — the repository's own unsigned-hash pattern is deliberately not used as proof.

**Detached signature (optional, accompanies rule (b)).** A detached Ed25519 signature over this document *as written to disk* is stored at `docs/audit/INDEPENDENT_BUILD_AUDIT.md.sig` (hex), with the corresponding raw public key at `docs/audit/INDEPENDENT_BUILD_AUDIT.pub` (hex). Signer id: `auditor-2026-10`. It was produced with the repository's own `dossier_pipeline/registry/keys.py` primitive (the AC-01 key-management path), from a throwaway key directory outside this repository. This signature corroborates document integrity and signer intent, but it is **not** an independent trusted-time attestation and the key is not externally witnessed (see F-16).
