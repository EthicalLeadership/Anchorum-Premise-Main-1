# Connector remediation plan ANCH-2026-10-12-01

**Remediating audit:** `docs/audit/CONNECTOR_AUDIT.md` (id **ANCH-2026-10-12-01**,
findings C-1…C-6).
**Companion:** `docs/audit/REMEDIATION_REPORT.md` (id ANCH-2026-10-02-01, findings
F-01…F-19), which is the audit of the pipeline as a whole.
**Branch:** `Anchorumzero_trust-on-Prem`
**Tree this plan was written against:** the working copy at
`/home/kark/anchorum-prem-main(1)/anchorum-prem-main`, with C-1 applied
(commits `0e9c273`, `3dc8c66`).
**Status of this document:** a plan, not a verification record. Every claim
below about current behaviour at the time of writing is taken from
`docs/audit/CONNECTOR_AUDIT.md` §5–§8 and from reading the code named in
Appendix A.

**Implementation status, appended after the fact.** `W1`, `W2`, `W3` and `W4`
have since been implemented on this branch, each with the pin this plan requires.
`W5` is implemented (see the table below), so `C-2` is now fully closed: the
zero-coverage outcome is explicit and the engine has a doctrinal vocabulary for
a case brief. The risk register is unchanged; the C2 warning at 1 of 8 scopes is
the risk register's coverage and is not affected by `W5`.
Read the workstream sections as the specification they were written to be, and
this table as what is on the tree.

| workstream | finding | state | pin |
|------------|---------|-------|-----|
| `W1` | `C-5` | Implemented. The record carries `source_sha256`, `source_bytes`, `source_filename`, `source_media_type`, `transport` and `synthesised_fields`; the synthetic wrapper is a function of the artifact alone, so unchanged bytes are recognised as a resubmission. | `tests/test_control_record_integrity.py::ArtifactIdentityInCommittedRecordTests`, `::DocumentResubmissionIdentityTests` |
| `W2` | `C-3` | Implemented. A non-email transport records `actor = unknown` with `classification_scope_warning` on the committed record, and a synthesised envelope field no longer counts towards provenance completeness. | `tests/test_control_record_integrity.py::ArtifactIdentityInCommittedRecordTests::test_record_does_not_invent_an_actor_for_a_document` |
| `W3` | `C-4` | Implemented. `interface/analysis.py` reads, segments and projects a stored artifact; `GET /evidence/{id}/analysis` and `POST /evidence/{id}/analyse` serve it; the item's status advances and carries an analysis block; custody entries state whether a chain was checked. | `tests/test_analysis.py`, `tests/test_evidence_analysis_api.py` |
| `W4` | `C-2` (a) | Implemented. Coverage is computed, and a majority-fallback or zero-match document carries an explicit warning instead of reading as "no legal concepts here". | `tests/test_analysis.py::test_uncovered_language_is_surfaced_as_a_warning` |
| `W5` | `C-2` (b) | Implemented. `lexicons/legal-doctrine-v1.yaml` (12 concepts, 42 patterns) bound through a second engine; 9 of 12 concepts fire on the brief; `DOCTRINE_OFFER` is a near miss asserted in the suite. The risk register is unchanged and the C2 warning stays at 1 of 8 -- that is the risk register's coverage, not the doctrine lexicon's. | `tests/test_doctrine_lexicon.py`, `tests/test_acceptance_brief.py::test_a5_doctrine_projection`, `::test_a6_analysis_record_carries_doctrine_block`, `::test_a6_doctrine_block_does_not_overwrite_risk_projection`, `::test_c7_api_analysis_returns_doctrine_block` |
| `W6` | `C-6` | Verify only; not re-checked in this pass. | |

Verification measured on this tree: the acceptance run in §3 is green, both as a
standalone run (16 of 16 checks) and in the suite, where
`tests/test_acceptance_brief.py` pins the same properties; `pytest` is 422
passed; `tsc --noEmit` exits 0; `vitest run` is 81 passed; `npm run build`
succeeds; `scripts/check_integrity.py --all`, `gitleaks dir .` and
`scripts/generate_sbom.py --check` all pass.

**Test inventory.** The workstream sections below name the test files they expect.
Several properties were pinned together in one file rather than one file each, so
this is where the planned names map to the pins that exist. The plan's own names
are kept here rather than edited out of the sections: a reader who searches for
one needs to land on the test, not on a gap.

| planned test file | where the pin lives now |
|-------------------|-------------------------|
| `tests/test_document_custody_identity.py` | `tests/test_control_record_integrity.py::DocumentResubmissionIdentityTests` (determinism, resubmission, artifact binding) |
| `tests/test_document_transport_provenance.py` | `tests/test_control_record_integrity.py::ArtifactIdentityInCommittedRecordTests` (transport, synthesised fields, actor, provenance, and the email-path regression guard) |
| `tests/test_document_api_hash_agreement.py` | as named; the cross-track tie, plus the assertion that the wrapper is not the artifact |
| `tests/test_analysis_scopes.py` | `tests/test_scopes.py` (segmentation, guarded by the real brief) |
| `tests/test_analysis_coverage.py` | `tests/test_analysis.py` (coverage counts, the warning, thresholds, refusals) |
| `tests/test_evidence_analysis_route.py` | `tests/test_evidence_analysis_api.py` (analysis route, re-analysis, item status, custody detail, search, timeline) |
| `tests/test_legal_doctrine_lexicon.py` | `tests/test_doctrine_lexicon.py` (shipped under this name; the suite is green) |

The frontend mapping in §7.4 has its own pin,
`interface/src/screens/EvidenceIntake.test.tsx`, which asserts that a refused or
failed read renders as a failure rather than as `done`.

**One finding left open deliberately, with the reason.** `check_inv_008` in
`dossier_pipeline/invariants.py` compares `actor` against the uppercase string
`"UNKNOWN"`, while `ActorType.UNKNOWN` is the lowercase `"unknown"`, so that
branch of the check cannot fire. Making it fire would newly require human review
for real mail whose actor is unrecognised but which otherwise scores high on
labels, which changes email-path behaviour beyond this plan's scope. It is
recorded here rather than silently repaired; §13 is where it belongs.

## 1. How to use this document

It is written to be handed out. Each workstream is self-contained: the finding it
closes, the evidence for it, the decision it needs, the exact files to touch, the
tests that must exist, and the condition that marks it done.

| | |
|---|---|
| **Workstream ids** | `W1`…`W6`. One workstream is one pull request, except `W5`, which is several. |
| **Finding ids** | `C-1`…`C-6` from the connector audit. `W1` closes `C-5`, `W2` closes `C-3`, `W3` closes `C-4`, `W4` closes half of `C-2`, `W5` closes the other half, `W6` is documentation only. |
| **Must do / may defer** | Each workstream has an explicit "Not in this workstream" list. Do not widen it without saying so on the plan. |
| **The pin rule** | Every fix needs a test that fails when the fix is reverted, and the person making the change must show it failing. This is the standard the F-01…F-19 remediation report set for itself (§8, "validated by mutation, not merely by passing") and it applies here. |
| **The honesty rule** | The connector audit's own verdict on the API is worth keeping: "These are honest refusals 501 with a named feature, not a silent empty list or a 500." Do not replace a named 501 with a stub that returns plausible-looking nothing. Replacing a 501 requires the feature to actually exist. |

Section 2 is the current state. Section 3 is the acceptance test the whole plan
exists to satisfy. Section 4 lists rules that apply to every change and are easy
to get wrong. Sections 5–10 are the workstreams. Sections 11–15 are sequencing,
hazards, decisions, exclusions and gates. Appendix A is the exact-target list.

## 2. State at the time of writing

This section is the historical starting point. The current state of the same
findings is the implementation-status table at the top of this document.

From `docs/audit/CONNECTOR_AUDIT.md` §3 and §13:

| id | severity | connector | state | closed by |
|----|----------|-----------|-------|-----------|
| C-1 | Critical | PDF / binary document ingestion | **Fixed** (`0e9c273`) | |
| C-2 | High | Legal lexicon projection (the "scopes") | **Fixed** | `W4` + `W5` |
| C-3 | High | Document classification in the dossier pipeline | Open | `W2` |
| C-4 | High | Product API → document analysis | Open | `W3` |
| C-5 | Medium | Custody identity of a submitted artifact | Open | `W1` |
| C-6 | Medium | Evidence signing key is a hard prerequisite | By design; now documented in `interface/README.md` | `W6` (verify only) |

What C-1 fixed, for context, because the remaining work builds on it:
`interface/pdf_text.py` (a dependency-free PDF text-layer extractor) and
`interface/submission.py` (one dispatcher that decides what an artifact is and
refuses what it cannot read honestly) now sit in front of both document entry
points, the GRIC inspector (`interface/gric_server.py`) and the dossier bridge
(`interface/document.py`). The brief's 14 distinguishing terms go from 0 found to
14 found, and U+FFFD replacement characters from 59,630 to 0. C-1 is the reason
the later workstreams have text to analyse at all.

## 3. Definition of done the acceptance test

The task that produced the audit defines done: *put the brief in through the
product as one item and have it analysed in its scopes.* `Angel v. Murray`,
322 A.2d 630 (R.I. 1974), 149,819 bytes, SHA-256
`c58fcf248ab877e75975c04606ab60aca294c2f36d2930df858400b0b9c31830`.

Two entry points reach this artifact and they are not the same entry point, so
the acceptance test has two tracks. Both must hold, and neither substitutes for
the other.

### Track A the product path (what the original request asked for)

Through `POST /cases/{id}/evidence` against the running API, with no manual
steps:

1. Upload returns 201 and the response's `hash` **is** `c58fcf24…`. This already
   holds today: `upload_evidence` hashes the uploaded bytes itself, so its
   `content_hash` is already the PDF's own SHA-256.
2. `processingStatus` is no longer the hard-coded `"stored"`; it reports what the
   analysis actually did (`extracted`, `unsupported`, `empty`,
   `skipped_oversize` or `failed`).
3. `GET /evidence/{id}/analysis` returns 200, not 501, with one entry per scope,
   each carrying either matched concepts or an explicit statement that the
   lexicon covered nothing there (C-4, `W3`).
4. `GET /cases/{id}/search?q=Murray` returns hits drawn from the brief's
   extracted text (C-4, `W3`).
5. `GET /cases/{id}/timeline` returns the case's real events, in order (C-4,
   `W3`).
6. A document of substantial length that matches no concept anywhere reports
   that fact explicitly rather than as a bare `canonical_projection_fallback`
   (C-2, `W4`).

### Track B the pipeline path (where C-5 and C-3 actually live)

Through `interface/document.py::process` and the `DossierPipeline` it drives.
This is a **different** entry point from Track A: `upload_evidence` never
constructs the pipeline, so no control record exists on the product path and the
acceptance test must not describe one as though it did. The record this track
names is the one `ingest_evidence` signs and `ControlPlane` commits.

1. The same bytes produce the same `raw_sha256`, `source_sha256` and
   `message_id` twice, and `source_sha256` is `c58fcf24…` (C-5, `W1`).
2. Resubmitting the identical bytes is a duplicate, including when the same bytes
   are submitted under a different filename (C-5, `W1`).
3. The committed record carries `source_sha256`, `source_bytes`,
   `source_filename`, `source_media_type`, `transport` and `synthesised_fields`
   as first-class fields, not as wrapper headers (C-5, `W1`).
4. No field in the committed record asserts a correspondent for a court filing:
   `transport` says `document`, `synthesised_fields` names
   `message_id`/`subject`/`sender`/`recipient`/`date`, and the actor is `unknown`
   rather than `insurer` (C-3, `W2`).

### The tie between the tracks

`tests/test_document_api_hash_agreement.py` (`W1`) asserts that Track A's
`Document.content_hash` and Track B's `source_sha256` are the same string for the
same bytes. That single pin is what stops the two halves drifting apart under a
new name, and it is the only place the tracks are required to meet.

All gates in §15 pass from the committed revision.

## 4. Cross-cutting rules read this before touching anything

These are the places the remaining work goes wrong quietly. Each is a property of
the code as it stands today, not a preference.

### 4.1 A new record field needs three edits, not one

The committed control-record payload is built in
`dossier_pipeline/control.py::ControlPlane._build_execution_context`, which reads
fields off the `AdapterResult` it is handed. `AdapterResult` is populated in
`dossier_pipeline/adapter.py::GovernanceAdapter.adapt` from the `EmailEnvelope`.
And `AdapterResult` is declared in `dossier_pipeline/contracts.py`.

So a field added to the envelope but not carried through `adapter.adapt` and
`_build_execution_context` **is silently absent from the signed record**. It will
appear in the pipeline's return value and nowhere else. The three files are:
`contracts.py` → `adapter.py` → `control.py`.

### 4.2 `validate_export_fields` is a denylist, not an allowlist

This is the reverse of what it sounds like, and it is a leak risk for the work in
`W3`. In `dossier_pipeline/trust_boundary.py`:

```python
def validate_export_fields(field_names):
    contract = get_contract()
    rejected = []
    for field_name in field_names:
        normalized = normalize_field_name(field_name)
        if contract.is_internal_only(normalized):
            rejected.append(normalized)
    return tuple(rejected)
```

Only fields named in `internal_only_fields` are rejected. A field that is in
neither list passes straight through `pipeline.py::_public_payload` and into
`export_json` / `export_markdown_summary`.

Consequence for `W3`: any payload field carrying raw case content extracted
text, per-scope projection text, the extracted-text digest **must be named in
`internal_only_fields`** or it will be exported in the clear. Digest values are
the ones most likely to be forgotten because they look like metadata (the audit
report's own F-18 pass found a hash being published as if it were inert).

The current contract is in Appendix A.5.

### 4.3 The privacy gate's field set is hard-coded, and that is the trap

`dossier_pipeline/privacy.py::_detect_excess_fields` compares the envelope
against a **hard-coded** set of envelope field names:

```python
envelope_fields = {
    "message_id", "subject", "sender", "recipient", "date", "body_text",
    "attachments", "raw_sha256", "message_key", "original_message_id",
    "ingest_timestamp",
}
```

Note that the transport-proof fields (`received_count`, `received_first_ts`,
`received_last_ts`, `received_chain_fingerprint_b64`) are already missing from
this set and `pipeline.py` already lists them in `allowed_fields`. They are
therefore never subject to the minimization check.

So adding envelope fields in `W1` will **not** break the privacy gate; the gate
will simply not see them. That is the wrong outcome. `W1` must extend this set so
the gate keeps being a gate, which in turn means `pipeline.py`'s `allowed_fields`
must list the new fields and if it does not, intake fails closed on the first
run, which is the correct direction to fail.

### 4.4 Adding payload keys does not break old chains

`ControlPlane.verify_chain` recomputes each record's hash from the **stored**
`payload_json`, so records written before a schema change keep verifying. New
fields change the hashes of new records only. Do not write a migration that
rewrites old records; that would destroy the property the chain exists for.

### 4.5 `raw_sha256` has one meaning today, and it is not the artifact

`EmailIntake.parse_email_bytes` ends with
`raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()` the bytes handed to
`process_email`. For a real `.eml` that is the artifact. For the document bridge
it is a synthesised wrapper. That ambiguity is C-5. Nobody may "fix" it by
redefining `raw_sha256`; the fix is to add the artifact identity alongside it and
say which is which (`W1`).

### 4.6 Do not widen a matcher to make a document match

The connector audit states this directly in §5 and it is repeated in `W4`/`W5`
below: broadening the matcher without broadening the lexicon "would trade a
visible fallback for a silent misclassification, which is worse". A
misclassification inside a signed record is not recoverable by the reader.

### 4.7 Work in the canonical tree

`docs/audit/REMEDIATION_REPORT.md` §4 records that the project exists at many
paths under `/home/kark`, and §6 records that two defects in this repository's
history were caused by operating on the wrong copy. Confirm the working copy
before starting.
## 5. W1 C-5: custody must bind the submitted artifact

**Finding.** Two runs of the same PDF through `interface/document.py::process`
produced `raw_sha256 = 2232297fbe9cbd16…` and `9d4a2d4802f0152e…`. The PDF's own
hash, `c58fcf248ab877e7…`, appears nowhere in the record. Dedup can never fire.

**Root cause.** `raw_sha256` is `sha256` of the synthetic `.eml` that
`_wrap_text_as_eml` builds, and that wrapper contains a `uuid4()` Message-ID and
a wall-clock `Date`. The recorded identity is a function of when the ingestion
ran, not of what was ingested.

**Decision taken by this plan.** Do both candidate repairs from the audit (§8),
because they are complementary and each is cheap:

1. **Add the artifact identity alongside the wrapper hash** both present, both
   named, so a reader can tell which is which.
2. **Make the wrapper deterministic** so `raw_sha256` stops moving and dedup
   starts working.

**Delivery mechanism: an explicit source argument, not wrapper headers.**
`process_email(raw_bytes)` gains an optional `source=`. The rejected alternative
is to carry the artifact hash as a synthetic header (`X-Anchorum-Source-SHA256`)
and let `intake.parse_email_bytes` read it back. That was rejected because a
header is caller-controlled: any submitter could set it and assert a source hash
the system never saw, turning the new binding into a forgeable one inside a
signed record. The source must be passed by the caller that actually read the
bytes.

### Steps

- [ ] **1.1 declare the fields** in `dossier_pipeline/contracts.py`. Keep them
      **flat**, matching the existing style of `EmailEnvelope` (which is already
      flat: `raw_sha256`, `message_key`, `original_message_id`,
      `ingest_timestamp`), and matching the hard-coded field set in
      `privacy.py` (rule 4.3). Add to `EmailEnvelope`:

      ```
      source_sha256: str = ""          # the submitted artifact's own SHA-256
      source_bytes: int = 0
      source_filename: str = ""
      source_media_type: str = ""
      transport: str = "email"         # "email" | "document"
      synthesised_fields: tuple[str, ...] = ()
      ```

      Document in the class docstring that `raw_sha256` is the hash of the bytes
      actually ingested (the transport envelope) and `source_sha256` is the hash
      of what the submitter handed over. For a real `.eml` the two are equal and
      `transport == "email"`; for the document bridge they are not, and
      `transport == "document"` says so.

- [ ] **1.2 default them in `dossier_pipeline/intake.py::parse_email_bytes`.**
      For a real message the artifact is the message:
      `source_sha256 = raw_sha256`, `source_bytes = len(raw_bytes)`,
      `source_media_type = "message/rfc822"`, `transport = "email"`,
      `synthesised_fields = ()`. The existing synthetic-Message-ID fallback for
      headerless mail is already content-derived
      (`<synthetic-{sha256(sender:date:raw_sha256)[:32]}@local>`) and stays as it
      is.

- [ ] **1.3 accept an override.** `DossierPipeline.process_email(raw_bytes, source=None)`
      applies the caller-supplied source to the parsed envelope **before**
      `self.privacy.validate(...)`, so the minimization gate sees the final field
      set. `_process_email_inner` carries the parameter through.
      `_safe_parse_envelope` (the failure path) must also produce a source, or
      an explicit empty one, so `_fail_with_stage` does not crash on the new
      fields.

- [ ] **1.4 make the wrapper deterministic** in `interface/document.py::_wrap_text_as_eml`:
      - `Message-ID` = `f"<{sha256(source_sha256).hexdigest()[:32]}@document.local>"`
        no `uuid4()`, no wall clock, and **no filename**. The filename must not
        enter the wrapper at all: `EmailSeenSet.claim_message` dedups on the
        normalized `message_id`, and `EmailIntake.normalize` compares that row's
        stored `raw_sha256`, so a wrapper that varies with the filename makes the
        same bytes under a new name a brand-new submission forever. The filename
        is carried as `source_filename` metadata instead, which is where a reader
        looks for it.
      - `Date` = a named module constant for synthetic wrappers, not
        `datetime.now(...)`.
      - Compute `source_sha256` in `process()` where the bytes are actually in
        hand. Three input paths, three definitions:
        `raw_bytes` → `sha256(raw_bytes)`; `file_path` → `sha256(path.read_bytes())`;
        `text=` → `sha256(text.encode("utf-8"))` with
        `source_media_type = "text/plain"` and `source_filename = ""`. The
        `text=` case has no artifact, and the record must say so rather than
        imply one.
      - Pass `transport="document"` and
        `synthesised_fields=("message_id", "subject", "sender", "recipient", "date")`
        into `process_email`. `subject` belongs in that tuple: `_wrap_text_as_eml`
        writes `Subject: {subject}` and `process()` defaults it to
        `"(interface submission)"`, so it is synthesised like the rest, and
        `W2`'s provenance check reads `envelope.subject`.

- [ ] **1.5 record the artifact in the evidence packet.** In
      `pipeline.py::_process_email_inner`, the `ingest_evidence(event_type="inbound_email", raw_payload={...})`
      call currently binds `message_id`, `raw_sha256`, `subject`, `sender`. Add
      `source_sha256`. That call is the signed custody record the audit refers
      to, and it is the half of the system that currently has no idea what the
      submitted file was.

- [ ] **1.6 carry them into the committed record.** Per rule 4.1, three
      places, all required: `contracts.AdapterResult` (declare), then
      `dossier_pipeline/adapter.py::GovernanceAdapter.adapt` (populate), then
      `dossier_pipeline/control.py::ControlPlane._build_execution_context`
      (commit). Add `source_sha256`, `source_bytes`, `source_filename`,
      `source_media_type`, `transport`, `synthesised_fields`.

      A useful detail: `adapter.adapt` also computes `payload_hash` over its
      `payload` dict. Because the source fields are in that dict, `payload_hash`
      now changes when the artifact changes, which is the property that was
      missing.

- [ ] **1.7 register them with the trust boundary.** In
      `dossier_pipeline/trust_boundary.py::DEFAULT_CONTRACT.exportable_fields`
      add `source_sha256`, `source_bytes`, `source_media_type`,
      `source_filename`, `transport`, `synthesised_fields`. All six belong in an
      export: they are the record's account of what was received, and
      `synthesised_fields` in particular is the honesty signal it must travel
      with the record, not be stripped from it.

- [ ] **1.8 keep the privacy gate a gate.** Per rule 4.3, add the six new
      names to BOTH the hard-coded `envelope_fields` set in
      `dossier_pipeline/privacy.py::_detect_excess_fields` AND the
      `allowed_fields` list passed by `pipeline.py` to `self.privacy.validate`.
      Do both or neither: adding only the first makes intake fail closed on the
      next run, which is the correct failure but not the intended change. While
      in that function, add the four transport-proof names that are already
      missing (`received_count`, `received_first_ts`, `received_last_ts`,
      `received_chain_fingerprint_b64`) they are currently invisible to the
      minimization check for no good reason.

### Tests (all required)

- [ ] `tests/test_document_custody_identity.py` (new):
      - the same PDF through `document.process` twice yields an identical
        `raw_sha256`, an identical `source_sha256`, and an identical
        `message_id`;
      - `source_sha256 == c58fcf24…` for the real brief, guarded by a
        file-existence check the way `tests/test_pdf_text.py` guards its real
        sample so a machine without the file does not fail;
      - a third identical submission returns `ResultStatus.DUPLICATE`. This is
        the assertion that fails if the wrapper goes back to `uuid4()`.
      - a synthetic PDF built in-test (no external sample) pins determinism
        unconditionally, so the property is not only tested where the sample
        exists.
      - the same bytes submitted under two **different filenames** yield the same
        `message_id` and the same `raw_sha256`, and the second submission is a
        duplicate. This is the assertion that fails if the filename goes back
        into the wrapper.
- [ ] `tests/test_control_record_integrity.py` (extend): a committed record
      carries `source_sha256` and `transport`, and `synthesised_fields` names all
      five invented fields (`message_id`, `subject`, `sender`, `recipient`,
      `date`).
- [ ] `tests/test_document_api_hash_agreement.py` (new): upload the same bytes
      through `POST /cases/{id}/evidence` and through `document.process`, and
      assert `Document.content_hash == source_sha256`. Without this pin the two
      halves of the system can drift apart again under a new name.

### Done when

Same bytes ⇒ same identity, twice; the PDF's own hash is in the record; a
resubmission is a duplicate; the API's `hash` and the pipeline's
`source_sha256` are the same string for the same file.

### Revert-proof

Restore `uuid.uuid4()` in `_wrap_text_as_eml` → the determinism test fails.
Delete `source_sha256` from `adapter.adapt` → the record test fails. Delete it
from `_build_execution_context` → same test fails. Delete it from
`exportable_fields` → the export test fails. Show each failing before reverting
the mutation.

### Not in this workstream

- Redefining `raw_sha256`. It keeps its meaning; a second field is added.
- Changing the dedup key. It stays `message_id` as `EmailSeenSet` normalizes it,
  with `raw_sha256` as the content guard; determinism, not a new key, is what
  restores dedup. Content-only dedup across *differing* message ids is explicitly
  not added here, because it would merge two submissions a caller meant to keep
  apart, and doing it safely needs a case or tenant scope decision first.
- A document-native pipeline entry point (see `W2`).

## 6. W2 C-3: the record must not invent a correspondent

**Finding.** The brief was classified `insurer` and the signed record contains
`sender: "interface@localhost"`, `recipient: "user@protonmail.com"` and a
`message_id`, all synthesised by the connector and indistinguishable in the
record from observed values.

**Where the invented values actually land** (this matters; the audit describes
"the payload" without naming which one):

- `sender` and `subject` go into the **signed evidence packet**, via
  `pipeline.py::_process_email_inner` →
  `ingest_evidence(event_type="inbound_email", raw_payload={"message_id", "raw_sha256", "subject", "sender"})`.
- `message_id`, `message_key`, `original_message_id`, `raw_sha256` go into the
  **committed control record**, via `adapter.adapt` →
  `control._build_execution_context`.
- `recipient`, `date`, `attachment_count`, `body_preview` appear only in the
  `PipelineResult.data` returned to the caller. They are not in the signed
  record today, and the plan does not add them.

So the fix is three-sided: label the invented values where they are recorded,
stop asserting a domain actor for a document, and stop letting invented metadata
count as provenance.

### Steps

- [ ] **2.1 the carrier is already in place** from `W1`: `transport` and
      `synthesised_fields` reach the evidence packet and the control record.
      `W2` consumes them; if `W1` is not merged, `W2` cannot be done honestly.
      **Do not start `W2` before `W1`.**

- [ ] **2.2 stop inventing provenance.** In
      `dossier_pipeline/provenance.py::ProvenanceCurator.curate`, the
      completeness check is:

      ```
      if not envelope.message_id: missing.append("message_id")
      if not envelope.date:       missing.append("date")
      if not envelope.sender:     missing.append("sender")
      if not envelope.subject:    missing.append("subject")
      ```

      For the document bridge all four are synthesised and non-empty, so
      `complete = True` and `human_review_required = False`. The record therefore
      claims complete provenance built entirely from values the connector made
      up. Change `curate` to treat a field listed in
      `envelope.synthesised_fields` as **absent for completeness purposes**, and
      to report which fields it did so for. For a document submission this yields
      `complete = False` and `human_review_required = True`, which is the honest
      answer for a court filing and is also the correct route (see 2.4).

      Note the consequence: `_process_email_inner` calls
      `assertions.validate("inv_008", ...)` with
      `output={"human_review_required": provenance.human_review_required}`. The
      check requires `human_review_required is True` when the actor is unknown
      or confidence is low. Making the synthesised fields count as missing
      satisfies that conjunct rather than violating it which is why 2.2 must
      land before or with 2.3, not after.

- [ ] **2.3 stop asserting a domain actor.** In
      `dossier_pipeline/classifier.py::EmailClassifier.classify`, add a
      transport-aware branch: when `envelope.transport != "email"`, set
      `detected_actor = ActorType.UNKNOWN` and add the reasoning
      `"document submission has no correspondent actor (transport=document)"`.
      Keep the label detection exactly as it is the labels are the substance
      and they are what routes the item. Keep the function pure (the same
      envelope twice must still classify identically: `inv_004` calls it twice
      and compares).

      `ActorType.UNKNOWN` already routes to `QUARANTINE_REVIEW` in
      `decision.py::DecisionEngine.transform` (`SILENCE MATRIX [UNKNOWN]`), which
      is the outcome the audit calls "the honest end of this path".

- [ ] **2.4 record the reason the classification is scoped, machine-readably.**
      A warning in `reasoning` is not enough: `trace` is in
      `internal_only_fields`, so it is stripped from exports. Add
      `classification_scope_warning: str = ""` to `ClassificationResult`
      (`contracts.py`), set it to `"document transport: actor not applicable"` in
      the 2.3 branch, carry it through `AdapterResult` + `adapter.adapt` +
      `_build_execution_context` (rule 4.1), and add it to
      `exportable_fields`.

- [x] **2.5 record the finding about `check_inv_008`.** **Resolved** (see below). The
      dead branch was fixed in `dossier_pipeline/invariants.py`, paired with the
      curator change described above; `ProvenanceCurator.curate` now sets
      `human_review_required` for an unrecognised actor, so the fixed check does
      not abort the run on real mail. The two new tests in
      `tests/test_assertions.py` isolate the actor branch specifically -- the
      existing low-confidence test fires on the confidence branch and would have
      passed with the bug present. This is D-6, and it is closed; the historical
      note follows for the record.

      The original text: In
      `dossier_pipeline/invariants.py`:

      ```python
      if (classification["confidence"] < 0.6
              or classification.get("actor") == "UNKNOWN"
              or provenance["confidence"] < 0.5
              or provenance.get("missing_fields")):
      ```

      `pipeline.py` passes `"actor": classification.actor.value`, and
      `ActorType.UNKNOWN = "unknown"` (lowercase, `contracts.py`). The comparison
      is against `"UNKNOWN"` (uppercase). **That branch can never fire**, so
      "an unrecognised actor must be flagged for human review" is not actually
      enforced today. Also note `provenance["confidence"]` is read in the same
      expression, but `_process_email_inner` passes
      `{"confidence": classification.confidence, "missing_fields": ...}` the
      key exists, so no `KeyError`, but it is the classification's confidence
      being checked twice under two names.

      Decide explicitly: either fix the case mismatch (in which case 2.2 is a
      hard prerequisite, because a fixed check plus `complete = True` would fail
      the run) or leave it and open a separate finding. Record the decision
      either way; a check that cannot fire must not be counted as coverage.

### Tests (all required)

- [ ] `tests/test_document_transport_provenance.py` (new): a document-bridge
      submission produces a record with `transport == "document"`,
      `synthesised_fields` naming
      `message_id`/`subject`/`sender`/`recipient`/`date`,
      `classification_scope_warning` non-empty, `actor == "unknown"`, and a
      route of `quarantine_review`. A real `.eml` submission produces
      `transport == "email"`, `synthesised_fields == ()`, and an unchanged actor
      this half is the regression guard for the whole email path.
- [ ] `tests/test_document_transport_provenance.py`: a document with a genuine
      sender (an `.eml`) still completes provenance normally pinning that the
      change keys on `synthesised_fields`, not on the transport alone.
- [ ] Extend the classifier tests: a court brief over the document transport does
      not come back as `insurer`.

### Done when

A court filing's committed record says, verifiably, that the email-shaped fields
were synthesised and that the actor is not applicable, and no consumer of the
record can mistake the invented values for observed ones.

### Revert-proof

Empty `synthesised_fields` in `_wrap_text_as_eml` → the transport test fails.
Remove the transport branch from `classify` → the brief is `insurer` again and
the test fails. Remove the synthesised-field check from `curate` → the
provenance test fails.

### Not in this workstream

- A native `process_document()` entry point for `DossierPipeline`. Every
  downstream stage (`privacy`, `provenance`, `adapter`, `policy`, `decision`) is
  written against `EmailEnvelope`; replacing it is a separate workstream with its
  own owner and its own audit. The only benefit over the above is naming, and it
  would touch every file in the pipeline at once.
- Changing the classifier's confidence formula (`0.3 + 0.15 × hits`). It is
  referenced by the F-16 note in `policy.py`. Flagged as a decision in §13.
## 7. W3 C-4: wire analysis into the product API

**Finding.** The API stores bytes faithfully 201, hash equal to the PDF's own
SHA-256, byte-identical download, `verify` passes and then nothing consumes it.
`processingStatus` stays `"stored"`, the evidence status stays `"received"`, the
custody chain reports `"not_checked"`, and every analysis surface is a named 501:
`timeline`, `case_search`, `case_audit`, `case_export`, `export_preview`,
`member_administration`.

**This is the workstream the original request was actually about.** C-2 is what
makes the analysis thin; C-4 is what makes it unreachable. Ship the reachability
first.

### 7.1 Architecture: two tiers, and the tier boundary is the point

The analysis path must **not** require `GDC_EVIDENCE_SECRET`.

- **Tier 1 extraction and projection. Always available.**
  `interface/submission.extract_text` (repaired by C-1) and
  `ccsp.verify.Engine.project` are pure and deterministic and touch no key
  material. There is no reason for "read this document and tell me what it says"
  to sit behind a signing secret.
- **Tier 2 committing a signed custody record into the control chain.
  Requires keys, fails closed, documented.** This is what
  `EvidenceStore.ingest`, `add_custody_event` and `export_bundle` do, and what
  `EvidenceSignerUnbound` correctly refuses without a key (F-02).

Keeping these separate is what lets the API analyse evidence on a machine with no
signing material, and it is also the honest answer to `chain: "not_checked"`:
tier 1 has no chain to walk. The API must say which tier it is in rather than
leaving a bare `not_checked` for a reader to interpret.

### 7.2 New modules

- [ ] **`interface/scopes.py`** IRAC scope segmentation: `CITATION`, `FACTS`,
  `PROCEDURAL_POSTURE`, `ISSUE`, `RULE`, `REASONING`, `HOLDING`,
  `DISTILLED_RULES`. One function, `split_scopes(text) -> list[Scope]` where
  `Scope` is `(name, text, start, end)`. Heading detection first (the brief's own
  headings), blank-line blocking second, whole-document fallback third.

  **Flagged as a product decision, not a mechanical port.** The connector audit
  §5 projects the brief through these eight scopes, but it did so in a throwaway
  probe (`/tmp/probe_final.py`) nothing in the repository implements this
  segmentation and no document in the repository defines it. The product owner
  has to confirm these are the scopes the product means before this becomes a
  pin. See §13.

- [ ] **`interface/analysis.py`** `analyse(stored_bytes, filename, media_type)
  -> AnalysisRecord`. Calls `submission.extract_text`, calls
  `scopes.split_scopes`, projects each scope through `interface.engine`, returns a
  JSON-safe record. It must not import FastAPI, a `Session`, or anything from
  `anchorum_api.py`; the API calls it, it does not know about the API.

  Two error behaviours, both required:
  - `submission.UnsupportedSubmission` (a `.docx`, a scan with no text layer) is
    a **recorded outcome**, not an exception that reaches the client: the record
    says `status: "unsupported"` with the dispatcher's own message, which already
    names the artifact type.
  - An unexpected failure is recorded as `status: "failed"` with the exception
    type and message. This is not the "silence errors" anti-pattern: the failure
    is stored and displayed, so the item never sits in a plausible-looking state
    that says nothing happened.

- [ ] **Reuse `interface/engine.py`.** It already loads the lexicon once
  (`@lru_cache`) and exposes `project_text`. Add a per-scope entry point rather
  than re-loading the lexicon per scope, and expose the two hashes
  `ProjectionResponse` already carries, named as it names them: `rules_hash` (the
  lexicon payload hash, `rules.hash` in `ccsp/verify.py`) and `config_hash`.
  There is no `lexicon_hash` field on that model; the API surfaces `rules_hash`
  under the key `lexiconHash` because to the product it identifies the lexicon,
  and that mapping must be written down rather than assumed. Those two values tie
  a stored analysis to the lexicon that produced it, and they are what makes
  re-analysis after a lexicon change (`W5`) meaningful.

### 7.3 Persistence

- [ ] **`dossier_pipeline/schema.py`** extend the `documents` table. The
  migration pattern already exists (`document_additions` plus
  `ALTER TABLE … ADD COLUMN`), pinned by
  `tests/test_interface_api.py::test_existing_sqlite_documents_get_local_storage_metadata_columns`.
  Add to both the `Document` model and `document_additions`:

  ```
  extract_status        VARCHAR(32) NOT NULL DEFAULT 'stored'
  extract_error         TEXT NOT NULL DEFAULT ''
  extract_sha256        VARCHAR(64) NOT NULL DEFAULT ''
  extract_chars         INTEGER NOT NULL DEFAULT 0
  extract_text_path     VARCHAR(255) NOT NULL DEFAULT ''
  analysis_json         TEXT NOT NULL DEFAULT ''
  analysis_rules_hash   VARCHAR(64) NOT NULL DEFAULT ''
  analysis_config_hash  VARCHAR(64) NOT NULL DEFAULT ''
  analysed_at           DATETIME
  ```

  Name the first of those `analysis_rules_hash`, not `analysis_lexicon_hash`: it
  stores the value `ProjectionResponse` calls `rules_hash`, and giving the column
  a different name for the same value is how the field-name confusion in §7.2
  starts. The API key stays `lexiconHash`, because that is the product-facing
  name, and §7.2 records the mapping.

  `extract_status` vocabulary: `stored` (not attempted), `extracted`,
  `unsupported`, `empty`, `skipped_oversize`, `failed`.

- [ ] **The extracted text goes in a sidecar file, not a column.**
  `<storage_key>.txt` beside the existing `<storage_key>.bin`, bound by
  `extract_sha256`. `stored_evidence_path` in `anchorum_api.py` already sanitises
  `storage_key` with `re.fullmatch(r"[0-9a-f]{32}", …)` and re-checks containment;
  the sidecar must use the same guard, not a new one. Do not put document text in
  the database: the local slice's database is the file someone will email around.

- [ ] **Bound the work.** Only extract below a configured size ceiling default
  25 MB, the ceiling `intake.EmailIntake.ARCHIVE_MAX_BYTES` already uses and
  record `skipped_oversize` above it. Extraction is synchronous in the upload
  request, and an unbounded synchronous PDF parse on a hostile upload is a
  denial-of-service on a single-process local API. State the ceiling in the
  README.

### 7.4 Wiring

- [ ] **`interface/anchorum_api.py::upload_evidence`** after the existing
  commit and `_custody_log`, run `analysis.analyse` on the stored bytes and update
  the document row. The response's `processingStatus` becomes the mapped extract
  status (`extracted` / `unsupported` / `empty` / `skipped_oversize` / `failed`)
  instead of the hard-coded `"stored"`. Add `sourceSha256` to the upload response,
  equal to the existing `hash` the same value `W1` puts in the pipeline record,
  which is what makes §3 item 3 testable.

- [ ] **Add `POST /evidence/{id}/analyse`** to re-run analysis without
  re-uploading. `W5` requires it: when the lexicon changes, every stored item's
  analysis is stale, and re-uploading case evidence to re-analyse it would
  destroy the meaning of the custody chain. Make `analyse` idempotent and record
  `analysed_at` each time.

- [ ] **Add `GET /evidence/{id}/analysis`.** Response shape:

  ```
  {
    "id": "E-…",
    "status": "processed" | "unsupported" | "empty" | "skipped_oversize" | "failed" | "pending",
    "reason": "",
    "source":  {"sha256": "c58fcf24…", "bytes": 149819,
                "mediaType": "application/pdf", "filename": "angel-v-murray.pdf"},
    "extract": {"status": "extracted", "chars": 4845, "sha256": "…", "error": ""},
    "projection": {"engineVersion": "ccsp-3.3.0", "lexiconHash": "…", "configHash": "…"},
    "coverage": {"scopesTotal": 8, "scopesMatched": 1, "scopesFallback": 7,
                 "ratio": 0.125, "warning": "lexicon covered 1 of 8 scopes"},
    "scopes": [
      {"scope": "FACTS", "chars": 2009, "conceptId": "LEGAL_ALLEGATION",
       "classification": "canonical_projection_insufficient", "admissible": false,
       "matchedConcepts": ["LEGAL_ALLEGATION"], "fallbackReason": null},
      {"scope": "ISSUE", "chars": 218, "conceptId": null,
       "classification": "canonical_projection_fallback", "admissible": false,
       "matchedConcepts": [], "fallbackReason": "all_unmapped"}
    ]
  }
  ```

  The `coverage` block is `W4`'s deliverable and is the field that stops seven
  empty scopes reading as "this document contains no legal concepts".

- [ ] **`_evidence_item`** add an `analysis` block (`status`, `scopesMatched`,
  `scopesTotal`, `warning`, `analysedAt`) and extend `badges`. Do not remove
  existing keys.

- [ ] **`status` on the evidence item.** The finding is literally that status
  "stays `received` indefinitely". Recommendation: let it advance
  `received` → `processed` / `unsupported` / `failed` with `badges` following.
  This is a **UI contract change**, and the types are not where an earlier draft
  of this plan said they were:
  - the evidence wire type and its `processingStatus` union live in
    `interface/src/adapter.ts`, the API boundary module, which is also where
    `TimelineEvent` is exported from. `interface/src/types.ts` holds only shell
    view models (`CaseSummary`, `CustodyEntry`, `DrawerObject`, `ShellBootstrap`)
    and must not be edited for this.
  - `screens/EvidenceIntake.tsx` currently maps progress with
    `result.value.processingStatus === "stored" ? "stored" : "done"`, so **every**
    value this plan introduces, including `failed` and `unsupported`, would
    render as `done`. That mapping must be made explicit before the new statuses
    ship, or `W3` converts a visible failure into a silent success.
  - `components/ProgressStrip.tsx` takes its own `IntakeState` plus a
    `failedStage` union of `"received" | "preserved" | "scanned" | "indexed"`,
    a different vocabulary from `extract_status`. Reconcile the two deliberately
    rather than passing one into the other.

  Coordinate with the frontend owner. §13 records the decision and the
  alternative (leave `status` as the intake lifecycle and expose analysis state
  only in the new `analysis` block).

- [ ] **`GET /evidence/{id}/custody`** keep the `chain` values (`not_checked`,
  `linked`, `broken`) because the UI type already encodes them, and add
  `chainDetail` explaining the value: with no signing material configured, the
  entry is the local audit row and there is no control chain on this host; with it
  configured and a record committed, the entry can be `linked`. Never report
  `linked` for a row that was not checked.
### 7.5 The 501s replace exactly the ones that can now be true

- [ ] **`GET /cases/{id}/search?q=`** → implement. Text now exists. A first cut is
  a bounded case-insensitive `LIKE` scan over the case's extracted-text sidecars,
  with a hit limit and a context window per hit. Prefer SQLite FTS5 if the
  interpreter's SQLite has it (check `PRAGMA compile_options` for `ENABLE_FTS5`
  at startup, fall back to `LIKE` otherwise).

  **The response body must stay a bare JSON array of `{id, excerpt}`.** That is
  the contract `screens/Search.tsx` already consumes: it declares
  `type Hit = { id: string; excerpt: string }` and assigns `r.value` straight to
  it as an array, so returning an object such as `{method, hits}` breaks the
  screen. Report which method ran in a response **header**
  (`X-Anchorum-Search-Method: like | fts5`), not in the body, because the two do
  not have the same matching semantics and the difference still has to be
  visible. The screen already has an `INDEX_BUILDING` path; keep it for the case
  where an index is expected but is not ready.
- [ ] **`GET /cases/{id}/timeline`** → implement from the data that exists:
  `audit_logs` (case-scoped, ordered) plus document `created_at`. Event kinds:
  `case_created`, `evidence_uploaded`, `evidence_verified`, `evidence_analysed`.
  Add `evidence_analysed` to the `_custody_log` call in the upload path.

  Each row must match the `TimelineEvent` the renderer already expects
  (`components/TimelineItem.tsx`): `id`, `event`, `date` (nullable), `precision`,
  `people` (non-empty array) and `evidenceId`. The renderer resolves `event`,
  `precision` and every `people` entry through the catalogues as
  `timeline.event.${event}`, `timeline.date_precision.${precision}` and
  `timeline.person.${person}`, so **every value emitted must have a key in both
  `interface/locales/en.json` and `fr.json`**, or the screen prints raw keys.
  `AuditLog.actor_username` is hard-coded `"system"` in `_custody_log`, so rows
  will carry `people: ["system"]`; that needs `timeline.person.system` to exist,
  and the route must not present "system" as a person's own action.

  **Keep 501 for chronology extracted from document content.** A court filing has
  dates in it, and pulling them out is a different feature. Returning the API's
  own audit rows while calling them a "case chronology" would be exactly the kind
  of mislabel this plan exists to avoid.
- [ ] **`GET /cases/{id}/audit`** → implement as projections over the API's own
  `audit_logs` plus each document's verification and analysis state. **State
  plainly what it is not:** it is not the dossier control chain. The control chain
  lives in the pipeline's SQLite stores (`{dossier_id}_chain.db`), verified by
  `ControlPlane.verify_chain` and anchored by `anchor.py`; this API slice has no
  control plane. A reviewer who reads "audit" and concludes the tamper-evident
  chain was checked has been misled, and the label must prevent that reading.
- [ ] **Leave `POST /cases/{id}/export`, `POST /cases/{id}/exports/preview` and
  the three `/admin/members` routes as named 501s.** They need the Barreau gate
  (`dossier_pipeline/barreau_gate.py`) and export gates that are not wired to the
  API, and `member_administration` needs a user model the local slice does not
  have (`schema.User` exists, but nothing administers it). Assign owners; §14
  records the decision. **Do not stub a preview.**

### 7.6 The export leak (rule 4.2, repeated because it is the sharpest risk here)

- [ ] If any extracted text ever enters a pipeline payload, add `extract_text`,
  `extract_error`, `analysis_json` and `extract_text_path` to
  `internal_only_fields` in `dossier_pipeline/trust_boundary.py` **in the same
  commit**. As designed, `W3` keeps document text in the API's own SQLite and
  sidecars and never puts it in a pipeline payload which is the right call but
  the moment someone adds "the extracted text" to `AdapterResult` for convenience,
  rule 4.2 means it is exported in the clear unless it is named internal-only.
- [ ] Also add `extract_sha256` and `analysis_rules_hash` if they enter a
  payload. A containment digest is not inert: it lets a reader confirm a guessed
  document against the record.

### 7.7 Do not write into a CWD-relative directory

`interface/document.py::_config` sets `cfg.setdefault("output_dir", "./output")`,
which resolves against whatever directory the process started in. The remediation
report's F-11 residual records that the CLI entry point now states the resolved
path, but the library layer takes what it is handed and this bridge hands it
`"./output"`. The API path must use a configured, absolute directory the same
root as `ANCHORUM_EVIDENCE_DIRECTORY`, or its own `ANCHORUM_OUTPUT_DIR`. Two
processes started from two directories must not write pipeline state to two
places; that is the F-11 defect exactly.

### Tests (all required)

- [ ] `tests/test_analysis_scopes.py` segmentation: the brief's eight scopes are
  recovered from its heading structure; a document with no headings falls back to
  whole-document; empty input raises rather than yielding an empty scope list
  (`project_text` already raises `ValueError("no non-empty blocks in input")`, and
  `analysis` must not convert that into a silent empty analysis).
- [ ] `tests/test_evidence_analysis_route.py` upload the brief; `GET
  /evidence/{id}/analysis` returns 200, eight scopes, `source.sha256` equal to the
  upload's `hash`, and a `coverage` block.
- [ ] `tests/test_evidence_analysis_route.py` upload a `.docx`;
  `processingStatus` is `unsupported`, the analysis route returns 200 with the
  dispatcher's message, and the item is not stuck at `"stored"`.
- [ ] `tests/test_evidence_analysis_route.py` upload a text file containing a
  known term; `GET /cases/{id}/search?q=` returns a bare array of
  `{id, excerpt}` and sets `X-Anchorum-Search-Method`.
- [ ] `tests/test_evidence_analysis_route.py` every `event`, `precision` and
  `people` value the timeline route emits has a matching key in both locale
  catalogues. Without this pin a new event kind ships as a raw
  `timeline.event.…` string in the UI.
- [ ] `tests/test_evidence_analysis_route.py` `GET /cases/{id}/timeline` returns
  `evidence_uploaded` and `evidence_analysed` for the case, in order.
- [ ] `tests/test_evidence_analysis_route.py` the still-unimplemented routes
  return 501 with a named feature. The concurrent actor's
  `test_unimplemented_product_routes_fail_explicitly` covers five of these today
  and must be narrowed to the three that remain, which is a change to a file this
  workstream does not own (see §12, hazard 1).
- [ ] `tests/test_document_api_hash_agreement.py` shared with `W1`.
- [ ] An oversize document reports `skipped_oversize` and does not attempt
  extraction.

### Done when

Upload → the bytes are analysed → the analysis is readable at a named route →
search and timeline return real data derived from that analysis → the three
features that still do not exist still say so, by name.

### Revert-proof

Delete the `analyse` call from `upload_evidence` → `processingStatus` is `stored`
again and the route test fails. Return `[]` from the search route → the search
test fails. Delete `sourceSha256` from the upload response → the hash-agreement
test fails.

### Not in this workstream

- Export and member administration (§7.5).
- Any change to what `ccsp` projects (that is `W4`/`W5`).
- Async or queued analysis. Synchronous in the request, with a size ceiling, is
  correct for a single-process local slice; a queue is a different product.
- Malware scanning. The README already says it is not provided, and a PDF text
  extractor is not a scanner. Say so again where analysis is described.
## 8. W4 C-2a: the zero-coverage outcome must be explicit

**Finding.** Seven of eight scopes return `canonical_projection_fallback` with
`concept_distribution = {}`, `unmapped = 1`, `admissible = false`. The audit's own
words: the failure is "silent by design: `canonical_projection_fallback` is a
legitimate 'no match' outcome and the model reports it as a fallback rather than
an error. An operator submitting this brief would be shown an empty projection,
which reads as 'this document contains no legal concepts' rather than 'the lexicon
does not cover this document's language.'"

**This is the half of C-2 that is a defect rather than a coverage gap, and it is
independent of any lexicon work.** Ship it before `W5`.

### Steps

- [ ] **4.1 compute coverage in the interface layer.** In
  `interface/analysis.py`, over the per-scope projections:

  ```
  coverage = {
    "scopesTotal":        len(scopes),
    "scopesMatched":      count(concept_id is not None),
    "scopesFallback":     count(classification == "canonical_projection_fallback"),
    "scopesInsufficient": count(classification == "canonical_projection_insufficient"),
    "ratio":              scopesMatched / scopesTotal,
    "warning":            None | "<sentence>",
  }
  ```

- [ ] **4.2 the warning rule.** Warn when a submission of substantial length
  matches nothing: `scopesMatched == 0` and total extracted characters above a
  named module constant (500 is a reasonable start, and the number must live in
  one place). Also warn when a majority of scopes fall back, because "1 of 8
  matched" reads nearly as badly as "0 of 8" when it is presented without comment.

- [ ] **4.3 put it where a person will see it.** The warning belongs in
  `GET /evidence/{id}/analysis`, in the `_evidence_item` `analysis` block, and in
  the upload response. A coverage number that exists only in a JSON field nobody
  renders has fixed nothing; hand the field to the frontend owner (§12, hazard 6).

- [ ] **4.4 do not touch `ccsp`.** Do not add a fallback reason to `_FB` in
  `ccsp/verify.py`. Its `T4` selftest asserts that no phantom fallback reason is
  emitted, and `canonical_projection_fallback` is a correct outcome *for the
  engine*. The missing signal is a property of how the product presents the
  result, so it belongs in the product layer.

### Tests

- [ ] `tests/test_analysis_coverage.py`: a document whose text matches nothing
  returns `scopesMatched == 0` and a non-null `warning`; the brief of §3 returns
  the per-scope counts and, until `W5`, a warning.
- [ ] `tests/test_analysis_coverage.py`: a short document that matches nothing
  does **not** warn the threshold is pinned in both directions.
- [ ] `tests/test_analysis_coverage.py`: `ccsp`'s own selftest still passes and
  `_FB` is unchanged, pinning that `W4` did not move the engine's semantics.

### Done when

A submission the lexicon cannot read produces a sentence that says so, wherever
the analysis is displayed, and the engine's own fallback semantics are untouched.

### Revert-proof

Return `warning: None` unconditionally → the coverage test fails. Set the
threshold to 0 → the short-document test fails.

### Not in this workstream

- The lexicon (`W5`).
- A confidence score for coverage. `ratio` is a count, not a claim about
  correctness; do not dress it up as one.
## 9. W5 C-2b: give the engine a vocabulary for a case brief

**Finding.** The brief is a contracts case brief offer, acceptance,
consideration, contract modification, unforeseen circumstances, the pre-existing
duty rule, `Restatement (Second) of Contracts` and the lexicon has no vocabulary
for how such a document is written. Only `FACTS` matched anything, and it scored
`canonical_projection_insufficient`, `admissible = false`.

**This is a coverage decision about the vertical, not a defect with one obvious
repair.** It has an owner who is not a coder, and it cannot be finished by widening
the matcher.

### 9.1 The decision that has to be made first

`lexicons/legal-v3.1.yaml` is a **risk register**. Its concepts carry:

- `forbidden: true` "a document that asserts this must not be relied on":
  `LEGAL_ESTABLISH_LIABILITY`, `LEGAL_CONFIRMED_VIOLATION`, `LEGAL_GUILT`,
  `LEGAL_WRONGFUL_CONDUCT`, `LEGAL_EVIDENCE_ASSERTS`,
  `LEGAL_QUANTIFIED_PROBABILITY`;
- `forbidden: false` hedged, negative, procedural and attributive concepts:
  `LEGAL_ALLEGATION`, `LEGAL_DENIAL`, `LEGAL_PENDING_REVIEW`, and the rest;
- `strength` `assertion`, `negative`, `hedged`, `procedural`, `attributed`,
  `opinion`, `qualified`.

Its whole apparatus `forbidden`, `admissible`, the `runtime.negation`
suppression and the `runtime.precedence` rules answers one question: **may this
text's assertions be relied on, or does it need human review?** That is a
risk-register question.

A case brief needs a **doctrinal taxonomy**: does the text discuss offer,
acceptance, consideration, contract modification, the pre-existing duty rule? That
is a descriptive question. `admissible = false` on a correctly identified
`CONSIDERATION` concept would mean nothing, and every consumer that reads
`admissible` `ProjectionResponse` in `interface/gric/schemas.py`, the GRIC
projection view, `SemanticEngineAdapter` would be reading a risk-register bit
applied to a doctrinal fact.

Two options. This is a product call and it must be made before any code is
written:

- **Option A (recommended) a second lexicon and a second engine.**
  `lexicons/legal-doctrine-v1.yaml`, concepts that are descriptive rather than
  forbidden, its own vertical scope, its own `Engine` instance, its own
  `rules_hash` and `config_hash`. `legal-v3.1.yaml` stays the risk register and
  does not move. `W5` then adds a *doctrine* projection alongside the existing
  *risk* projection, and the analysis route reports both, labelled.
  Cost: two artifacts, two hashes, a named vertical. Benefit: neither register's
  semantics are corrupted, the existing pins do not move, and every projection
  says which question it answers.
- **Option B extend `legal-v3.1.yaml`.** Cheaper, one artifact, but it mixes two
  registers in one file, changes what `admissible` means for existing consumers,
  and moves `rules_hash`/`config_hash`, invalidating the pins in
  `tests/test_semantic_adapter.py` and the projection tests. If chosen, the pin
  update must be a deliberate, visible commit, and the old lexicon file must stay
  on disk so previously computed hashes remain verifiable.

Either way: **a new versioned file, not an in-place edit.** `load_lexicon` in
`ccsp/verify.py` hashes the whole concept-and-pattern payload into `rules.hash`,
and that hash is carried into every projection's `rules_hash` and into the
engine's `config_hash`, so the change is visible wherever a projection is read.
### 9.2 Scope of the concepts the owner's list, not the coder's

Under Option A the doctrine lexicon needs concepts for at least: offer,
acceptance, consideration, contract modification, the pre-existing duty rule,
unforeseen circumstances / impracticability, benefit conferred, cited authority
(`Restatement`, a reporter citation such as `322 A.2d 630`), procedural posture
(appeal, trial, summary judgment), the issue framing, and the holding. Each with
`surface_pattern`s written in **the register a case brief is written in**, not the
register of a demand letter that mismatch is the audit's actual point.

The lexicon format gives the owner a way to state the requirement precisely: every
concept in `legal-v3.1.yaml` carries a `tests:` block with positive and negative
examples, plus the file-level `adversarial_tests`, `splitter_tests` and
`benign_tests` blocks. The doctrine lexicon must carry the same shape, and the
negative examples are the load-bearing ones. A case brief *discusses* liability
without *asserting* it, so a pattern that fires on "The Court considered whether
the evidence supported the plaintiff's claim" is a false positive and that
sentence is already a `benign_tests` entry in the risk register, which is the
precedent to follow.
### 9.3 Steps

- [ ] **5.1 the owner produces the concept list** (names, one-line definitions,
  positive and negative examples). This is the blocking step; nothing below can
  start without it.
- [ ] **5.2 author the lexicon** (Option A: `lexicons/legal-doctrine-v1.yaml`)
  with the same structure as `legal-v3.1.yaml`: `version`, `runtime`, `concepts`,
  `lexicon`, `tests`.
- [ ] **5.3 a second engine binding** in `interface/engine.py`, following the
  pattern `dossier_pipeline/governance/semantic_adapter.py::build_for_vertical`
  already establishes (`lexicon_path`, `vertical_id`, `engine_class`, and the
  lexicon hash read from the engine's `rules_hash`, which `ccsp/verify.py`
  derives from `rules.hash`).
- [ ] **5.4 report both projections** in `interface/analysis.py` and in
  `GET /evidence/{id}/analysis`, each labelled with the question it answers and
  each with its own `lexiconHash`/`configHash`. `W4`'s `coverage` block becomes
  per-projection.
- [ ] **5.5 update the pins deliberately** (Option B) or add new ones (Option
  A). In both cases show the pin failing before updating it, and record in the
  commit message which hash moved and why.
- [ ] **5.6 re-analysis.** After the lexicon change, `POST /evidence/{id}/analyse`
  on a previously analysed item updates `analysis_json` and
  `analysis_rules_hash` without touching the stored bytes or the custody chain.
  This is the reason `W3` adds that route, and it is what makes a lexicon change
  safe to ship.
### Tests

- [ ] `tests/test_legal_doctrine_lexicon.py`: every concept has at least one
  positive and one negative example and every example behaves as declared, driven
  from the file's own `tests:` block so the lexicon and its tests cannot drift.
- [ ] `tests/test_legal_doctrine_lexicon.py`: the doctrine projection returns
  concepts on the brief's `ISSUE`, `RULE`, `REASONING` and `HOLDING` scopes. The
  test names the expected concepts explicitly rather than asserting "non-empty"
  the point is that the taxonomy matches the document, not that the engine
  emitted something.
- [ ] `tests/test_legal_doctrine_lexicon.py`: the brief does **not** fire any
  additional `forbidden` concept in the *risk* lexicon pinning that the doctrine
  work did not loosen the risk register.
- [ ] `tests/test_semantic_adapter.py` and the projection tests: updated pins, or
  unchanged under Option A. Either way the suite is green and the pin change is
  visible in the diff.

### Done when

The brief's doctrinal scopes return the concepts the owner's list says they
should, the risk register's behaviour is unchanged, and every projection reports
which lexicon and which config produced it.

### Revert-proof

Delete the doctrine lexicon → the engine binding raises and the tests fail. Point
the doctrine engine at `legal-v3.1.yaml` → the concept assertions fail.

### Not in this workstream

- Document types other than a case brief.
- Any change to `ccsp/verify.py`.
- Widening `runtime.matching`, `runtime.negation` or `runtime.precedence` to make
  the brief match. Rule 4.6.
## 10. W6 C-6: the signing requirement is documented, and stays accurate

`interface/README.md` was updated in the C-1 pass to state that the document path
**signs** and therefore fails closed without `GDC_CONTROL_SIGNING_KEY` and
`GDC_EVIDENCE_SECRET` (32+ characters), and that a short secret is refused rather
than stretched. That is the whole of the C-6 work.

- [ ] Verify the README still matches the code after `W3`. `W3` deliberately makes
  the **analysis** path key-free and leaves the **commit** path fail-closed; the
  README must distinguish the two, or an operator will read "this needs a secret"
  and conclude the analysis does too.
- [ ] Add the size ceiling from `W3` §7.3 to the same section.
- [ ] Add one line stating that analysis is not malware scanning and not
  authenticity: the extractor reads a text layer, and a `pass` from
  `/evidence/{id}/verify` means the stored bytes still hash to what was recorded,
  nothing more.

No code change in this workstream unless the README turns out to be wrong.

## 11. Sequencing, ownership and work-in-progress

| order | workstream | closes | depends on | parallel-safe |
|---|---|---|---|---|
| 1 | `W1` | C-5 | | |
| 2 | `W2` | C-3 | `W1` (it consumes `transport`/`synthesised_fields`) | `W3` |
| 3 | `W3` | C-4 | `W1` (hash agreement) | `W2`, `W5` |
| 4 | `W4` | C-2a | `W3` (it edits the module `W3` creates) | `W5` |
| 5 | `W5` | C-2b | the owner's concept list | `W3`, `W4` |
| 6 | `W6` | C-6 (verify) | `W3` | |

**Rationale for this order.**

- `W1` first because `W2` records what `W1` carries, and because `W3`'s hash
  agreement test needs a `source_sha256` to agree with.
- `W3` before `W4`, not the other way round. `W4` step 4.1 computes coverage
  inside `interface/analysis.py`, and that module does not exist until `W3`
  creates it, so a `W4`-first order is circular. This reverses an ordering chosen
  earlier in this plan's drafting, so record the cost instead of hiding it: the
  analysis route now lands one commit before the coverage block, and the first
  version an operator can see is the one that reads as "no concepts found".
  `W3` and `W4` should therefore ship in the same release. If they cannot, `W3`
  ships with `coverage.scopesTotal` populated but `coverage.warning: null` and
  **no operator-facing badge**, so nothing presents a zero as a finding before
  `W4` fills the warning in.
- `W5` last and in parallel because it is the only workstream blocked on a product
  decision, and nothing else can start on it until that decision exists. `W3`'s
  `POST /evidence/{id}/analyse` exists specifically so `W5` does not have to
  re-ingest evidence.

**Ownership.** Three roles, and a workstream should name one person for each:

1. **Pipeline owner** `W1`, `W2`. Touches `dossier_pipeline/**` and the signed
   record; needs the record-schema discipline in §4.
2. **Interface owner** `W3`, `W4`, `W6`. Touches `interface/**` and
   `dossier_pipeline/schema.py`.
3. **Vertical owner** (not a coder) `W5`. Owns the lexicon's concept list and
   the register decision in §9.1.

**Work-in-progress limit: two.** `W1` must merge before `W2` starts, and `W1`
must merge before `W3`'s hash test can pass. Everything else can overlap. `W5` can
run the whole time without touching code until §9.1 is answered.

**Branch discipline.** One workstream per branch, and each branch carries its
tests. `W1` and `W2` both change the committed record's payload, so they change
what `tests/test_control_record_integrity.py` sees; if they land together the
pins are easier to read, but they must be separable.
## 12. Coordination hazards

Six things will bite during this work. Each is a fact about the tree, not a
warning in general.

1. **`tests/test_interface_api.py` is untracked and belongs to a concurrent
   actor.** It asserts exactly what `W1` and `W3` change:
   `processingStatus == "stored"`, `status == "received"`,
   `badges == ["received"]`, `custody[0]["chain"] == "not_checked"`, and that
   five routes return 501. `W3` invalidates all of those assertions. Either that
   file is committed first and updated in the same change as `W3`, or `W3`'s
   owner takes it over. Two actors editing one untracked file is the F-19 hazard
   in miniature, and `docs/audit/REMEDIATION_REPORT.md` §6 records that this
   class of collision has already produced two defects in this repository.

2. **The trust-boundary lists are easy to get backwards.** `exportable_fields`
   and `internal_only_fields` both need updating for every new payload field, and
   the failure modes are opposite: forget `exportable_fields` and the field
   vanishes from exports; forget `internal_only_fields` and case content is
   exported in the clear (rule 4.2). Getting one right is not evidence the other
   is.

3. **The privacy gate's hard-coded set must move with the envelope** (rule 4.3).
   Add to `envelope_fields` and to `allowed_fields` in the same commit, or the
   next intake fails closed.

4. **The lexicon pins move under `W5`.** `tests/test_semantic_adapter.py` and the
   projection tests carry hashes derived from `rules.hash`. Update them in the
   `W5` commit with a note saying which hash moved, not in a follow-up cleanup
   commit.

5. **The two halves of the system must keep agreeing on the artifact hash.**
   `W1`'s `source_sha256` and the API's `Document.content_hash` must be the same
   string for the same bytes. That is what
   `tests/test_document_api_hash_agreement.py` pins. Without it the C-5
   disagreement returns under a new name.

6. **The UI is another actor's territory.** The evidence wire type and its
   `processingStatus` union live in `interface/src/adapter.ts`, not in
   `src/types.ts` (which holds only shell view models). The screens involved are
   `screens/EvidenceViewer.tsx`, `screens/EvidenceIntake.tsx`,
   `screens/Search.tsx`, `screens/Timeline.tsx`, `components/TimelineItem.tsx`
   and `components/ProgressStrip.tsx`. They need the new `analysis` fields, the
   `status`/`badges` change, an explicit replacement for
   `processingStatus === "stored" ? "stored" : "done"` (which would otherwise
   render `failed` as `done`), and locale keys for every timeline value. Hand
   over the exact shapes from §7.4 and §7.5 rather than editing their files, and
   let them own the interface contract change.

Two more, lower severity but real:

7. **The work must happen in the canonical working copy.** §4.7.
8. **`interface/document.py` sets `ANCHORUM_ENV=local` at import.**
   `_os.environ.setdefault("ANCHORUM_ENV", "local")` runs on import of that
   module, so any test or script that imports it inherits a local environment
   regardless of what the test intended. Nothing in this plan depends on it, but
   a test that wants to exercise a non-local environment path cannot do so
   through this module.
## 13. Decisions requiring an owner's call

Each of these has more than one defensible answer, and picking one silently is
how the audit's own complaint a choice made without the evidence being visible
gets repeated. Record the decision in the commit message or in this document.

| # | Decision | Options | This plan recommends | Who |
|---|---|---|---|---|
| D-1 | `W5`: doctrine vocabulary | A: second lexicon + second engine. B: extend `legal-v3.1.yaml` | **A.** Keeps the risk register's semantics intact and does not move its pins | Vertical owner |
| D-2 | `W5`: the concept list itself | coverage of the contracts curriculum | Owner-produced list with positive **and negative** examples per concept | Vertical owner |
| D-3 | `W3`: the scope model | the eight IRAC scopes from the audit's probe, or something else | Confirm the eight before `scopes.py` becomes a pin | Product owner |
| D-4 | `W3`: the tier split | analysis key-free / commit keyed, or everything behind the secret | **Key-free analysis, keyed commit.** Otherwise nothing is analysable on a machine without signing material | Product owner |
| D-5 | `W3`: the evidence-item `status` | advance it (`received` → `processed`), or keep `received` and carry analysis state only in the new block | **Advance it** the finding names the frozen status but this is a UI contract change, so the frontend owner must agree | Frontend owner |
| D-6 | `W2`: `check_inv_008`'s dead branch | fix the case mismatch (needs 2.2), or record it and leave it | **Fixed.** The comparison uses `ActorType.UNKNOWN.value` and normalises the input; the paired curator change landed in `provenance.py` so the check does not fail closed on real mail. Two tests isolate the actor branch. The redundant `provenance["confidence"] < 0.5` check was dropped as subsumed. | Pipeline owner (done) |
| D-7 | `W1`: what `text=` submissions bind to | hash of the UTF-8 text, or refuse `text=` on the document path | **Hash the UTF-8 text and label it `text/plain`.** Refusing would break the GRIC inspector's `project_submit` path | Pipeline owner |
| D-8 | `W3`: the size ceiling | 25 MB (mirrors `ARCHIVE_MAX_BYTES`), or lower | **25 MB**, stated in the README | Interface owner |
| D-9 | `W2`: the classifier's confidence formula | leave `0.3 + 0.15 × hits`, or give the classifier a model that can express uncertainty | **Leave it in this pass.** The actor and the scope warning carry the honesty signal; changing the formula touches `policy.py`'s F-16 note | Product owner |

## 14. Explicitly out of scope for this plan

Stated so that nobody closes a workstream and finds these still on the list
unaccounted for.

- **`case_export`, `export_preview`, `member_administration`.** They keep their
  named 501s. `case_export` and `export_preview` need the Barreau gate and the
  export gates wired to the API; `member_administration` needs user
  administration the local slice does not have. Each needs an owner and its own
  plan.
- **A native `process_document()` entry point for `DossierPipeline`.** §6.
- **`docx`, `odt`, image and video readers.** `interface/submission.py` refuses
  them correctly and names the type. Adding readers is separate work, and the
  refusal is currently the honest behaviour.
- **OCR for scans.** `pdf_text.NoTextFound` correctly refuses a PDF with no text
  layer. OCR is a different component with different failure modes, and adding it
  to a plan about *whether the analysis runs at all* would be a category error.
- **Asymmetric signing for the control chain.** Recorded as accepted risk in
  `docs/audit/REMEDIATION_REPORT.md` §7.1. `W1` and `W2` add fields to records
  signed with HMAC; they do not change the signing scheme, and this plan does not
  either.
- **Any change to `ccsp/verify.py`.** Its fallback reasons, negation and
  precedence rules are pinned by its own selftest and are correct for what they
  do. `W4` works around its semantics rather than changing them.
- **The other audit's residuals** (F-19's machine-level path ambiguity,
  `_command` classifier egress, interpreter version pinning). Named in
  `docs/audit/REMEDIATION_REPORT.md` §7; not this plan's subject.

## 15. Gates and the verification standard

Run from the **committed** revision, not the working tree, and state which one
each number came from the remediation report's §8 explains why that distinction
matters here: the working tree carries another actor's untracked
`tests/test_interface_api.py`, so the two counts differ and only the committed one
travels with a clone.

| gate | command | expected |
|---|---|---|
| Integrity self-test | `python3 scripts/check_integrity.py --selftest` | 6/6 |
| Integrity, all source | `python3 scripts/check_integrity.py --all` | OK |
| Secret scan | `gitleaks dir . --config .gitleaks.toml` | no findings |
| Secret scan, staged | `gitleaks git --staged --config .gitleaks.toml` | exit 0 |
| SBOM / lock drift | `python3 scripts/generate_sbom.py --check` | no drift |
| Python suite | `python3 -m pytest -q -p no:cacheprovider` | all pass, 0 skipped, count stated per tree |
| Type-check | `npx tsc --noEmit` in `interface/` | exit 0 |
| UI suite | `npx vitest run` in `interface/` | all pass |
| Build | `npm run build` in `interface/` | exit 0 |

**The mutation standard.** Every pin added by this plan must be shown failing
before it is trusted. The pattern to copy is in
`docs/audit/REMEDIATION_REPORT.md` §8: for each new test, apply the mutation the
test is supposed to catch, run it, confirm exactly that test fails and the others
pass, then revert the mutation and confirm `git diff` is clean. A test that has
never been seen to fail is not evidence, and this plan does not count it as such.

**The end-to-end run.** Both tracks of §3, the product path against the running
API and the pipeline path through `interface/document.py`, on the real brief,
start to finish, with the output pasted into the closing report. That is what
"the brief can be put in and analysed" means; nothing less closes `C-4`.
## Appendix A exact targets

Every path is relative to the repository root. The symbol names are the functions
or fields the work touches.

### A.1 `interface/`

| file | symbol | what changes |
|---|---|---|
| `document.py` | `_wrap_text_as_eml` | deterministic `Message-ID` and `Date`; takes the source artifact |
| `document.py` | `_submit_text` | passes `source=` and `transport="document"` |
| `document.py` | `process` | computes `source_sha256` on all three input paths |
| `document.py` | `_config` | `output_dir` must not stay CWD-relative (§7.7) |
| `document.py` | module top | `_os.environ.setdefault("ANCHORUM_ENV", "local")` runs on import (§12.8) |
| `submission.py` | `extract_text`, `UnsupportedSubmission`, `UNIMPLEMENTED_SUFFIXES`, `TEXT_SUFFIXES` | read as-is; `W3` consumes them, it does not change them |
| `engine.py` | `engine`, `project_text`, `lexicon_summary`, `LEXICON_PATH` | per-scope entry point; expose `rules_hash`/`config_hash` (`ProjectionResponse` has no `lexicon_hash`); `W5` adds a second binding |
| `scopes.py` | *(new)* | `split_scopes` |
| `analysis.py` | *(new)* | `analyse`, coverage computation, warning rule |
| `anchorum_api.py` | `upload_evidence` | run analysis; advance `processingStatus`; add `sourceSha256` |
| `anchorum_api.py` | `_evidence_item` | `analysis` block, `badges` |
| `anchorum_api.py` | `get_evidence_custody` | `chainDetail` |
| `anchorum_api.py` | `get_timeline`, `search_case`, `get_case_audit` | implement |
| `anchorum_api.py` | `export_case`, `preview_case_export`, `list_members`, `invite_member`, `change_member_role` | leave as named 501s |
| `anchorum_api.py` | `stored_evidence_path` | the sidecar must reuse this guard |
| `anchorum_api.py` | *(new routes)* | `POST /evidence/{id}/analyse`, `GET /evidence/{id}/analysis` |
| `gric/schemas.py` | `ProjectionResponse` | add the coverage/warning fields the API surfaces |
| `src/adapter.ts` | the evidence wire type and its `processingStatus` union, `TimelineEvent`, the search hit type | new analysis fields; `status`/`badges` change (frontend owner) |
| `src/types.ts` | `CaseSummary`, `CustodyEntry`, `DrawerObject`, `ShellBootstrap` | shell view models only; **not** where the evidence type lives |
| `src/screens/EvidenceIntake.tsx` | the `processingStatus === "stored" ? "stored" : "done"` mapping | make it explicit for the new statuses, or `failed` renders as `done` (frontend owner) |
| `src/components/ProgressStrip.tsx` | `IntakeState`, `failedStage` | reconcile its vocabulary with `extract_status` (frontend owner) |
| `locales/en.json`, `locales/fr.json` | `timeline.event.*`, `timeline.date_precision.*`, `timeline.person.*` | add a key for every value the new timeline emits (frontend owner) |
| `README.md` | signing section | distinguish analysis from commit; size ceiling; limits |

### A.2 `dossier_pipeline/`

| file | symbol | what changes |
|---|---|---|
| `contracts.py` | `EmailEnvelope` | `source_sha256`, `source_bytes`, `source_filename`, `source_media_type`, `transport`, `synthesised_fields` |
| `contracts.py` | `ClassificationResult` | `classification_scope_warning` |
| `contracts.py` | `AdapterResult` | carry the six envelope fields + the scope warning |
| `intake.py` | `parse_email_bytes` | default `source_*`, `transport="email"`, `synthesised_fields=()` |
| `intake.py` | `EmailSeenSet.claim_message` | unchanged; deterministic ids restore dedup |
| `pipeline.py` | `process_email`, `_process_email_inner` | accept and apply `source=` before the privacy gate |
| `pipeline.py` | `_safe_parse_envelope` | must not crash on the new fields |
| `pipeline.py` | the `ingest_evidence(...)` call | add `source_sha256` to `raw_payload` |
| `pipeline.py` | the `privacy.validate(...)` `allowed_fields` list | add the six new names |
| `pipeline.py` | `_public_payload` | mechanism unchanged; rule 4.2 governs what it lets through |
| `classifier.py` | `EmailClassifier.classify` | transport-aware actor; keep purity for `inv_004` |
| `provenance.py` | `ProvenanceCurator.curate` | synthesised fields do not count as provenance |
| `adapter.py` | `GovernanceAdapter.adapt` | populate the new payload fields; `payload_hash` then covers them |
| `control.py` | `ControlPlane._build_execution_context` | commit the new payload fields |
| `control.py` | `_signing_key_id` | still defaults `local-dev` F-01 residual, **not** this plan |
| `privacy.py` | `_detect_excess_fields` | extend the hard-coded `envelope_fields` set |
| `trust_boundary.py` | `DEFAULT_CONTRACT` | `exportable_fields` / `internal_only_fields` |
| `schema.py` | `Document`, `init_schema` / `document_additions` | the nine new columns |
| `invariants.py` | `check_inv_008` | the `"UNKNOWN"` / `"unknown"` mismatch (§6, D-6) |
| `governance/semantic_adapter.py` | `build_for_vertical` | the pattern for the second engine binding |
| `evidence.py` | `EvidenceSignerUnbound`, `EvidenceStore.ingest` | unchanged; it is the fail-closed boundary `W3` stops crossing |
| `barreau_gate.py` | `BarreauGate` | not wired in this pass (§7.5) |
### A.3 `ccsp/` and `lexicons/`

| file | what changes |
|---|---|
| `ccsp/verify.py` | **nothing.** `_FB`, `Engine.project`, `_canon`, `load_lexicon`, `_ph` are read, not modified |
| `lexicons/legal-v3.1.yaml` | unchanged under Option A; extended under Option B (with pin updates) |
| `lexicons/legal-doctrine-v1.yaml` | *(new under Option A)* the owner's concept list |

### A.4 Tests

| test | workstream | new / extended |
|---|---|---|
| `tests/test_document_custody_identity.py` | `W1` | new |
| `tests/test_document_api_hash_agreement.py` | `W1` + `W3` | new |
| `tests/test_control_record_integrity.py` | `W1` | extended |
| `tests/test_document_transport_provenance.py` | `W2` | new |
| `tests/test_analysis_scopes.py` | `W3` | new |
| `tests/test_evidence_analysis_route.py` | `W3` | new |
| `tests/test_analysis_coverage.py` | `W4` | new |
| `tests/test_legal_doctrine_lexicon.py` | `W5` | new |
| `tests/test_semantic_adapter.py` | `W5` | pins updated, or unchanged |
| `tests/test_interface_api.py` | `W3` | **not owned by this plan** see §12.1 |

### A.5 The trust boundary contract as it stands

`dossier_pipeline/trust_boundary.py::DEFAULT_CONTRACT`, verbatim field lists, so
the additions in `W1` and `W2` are made against the real thing:

```
internal_only_fields = (
    "decision_reasoning", "decision_trace", "payload_hash",
    "previous_hash", "control_hash", "trace",
)

exportable_fields = (
    "dossier_id", "message_key", "message_id", "subject", "sender",
    "recipient", "date", "actor", "labels", "confidence", "route",
    "policy", "record_hash", "raw_sha256", "body_preview",
    "received_count", "received_first_ts", "received_last_ts",
    "received_chain_fingerprint_b64",
)

regulated_fields = (
    "original_message_id", "ingest_time", "missing_fields",
    "human_review", "quarantine",
)
```

`W1` adds `source_sha256`, `source_bytes`, `source_filename`,
`source_media_type`, `transport`, `synthesised_fields` to `exportable_fields`.
`W2` adds `classification_scope_warning` to `exportable_fields`. `W3` adds
`extract_text`, `extract_error`, `analysis_json`, `extract_text_path` to
`internal_only_fields` **only if** any of them ever enters a pipeline payload.

Note the shape of `validate_export_fields`: it returns the fields to *drop*, so
`regulated_fields` is not consulted by that function at all it is descriptive
metadata for other readers. Do not assume adding a name there removes it from an
export.
## Appendix B reproduction commands

These are the commands the audit used, plus the ones this plan adds. The probe
scripts are throwaway and are not committed; §15's gate results are what is
reproducible from the committed tree alone.

```bash
# 1. The extractor alone (before/after counts)
python3 /tmp/probe_final.py

# 2. The document connector end to end (needs both signing keys)
ANCHORUM_ENV=local OUTPUT_DIR=/tmp/casebrief/out \
GDC_CONTROL_SIGNING_KEY="<32+ chars>" \
GDC_EVIDENCE_SECRET="<32+ chars>" \
python3 /tmp/probe_payload.py

# 3. The product API
ANCHORUM_LOCAL_API_MODE=1 \
ANCHORUM_DATABASE_URL=sqlite:////tmp/casebrief/api.db \
ANCHORUM_EVIDENCE_DIRECTORY=/tmp/casebrief/api_evidence \
python3 -m uvicorn interface.server:app --host 127.0.0.1 --port 8011
python3 /tmp/api_probe.py        # exercises every route in section 7

# 4. The gates
python3 scripts/check_integrity.py --selftest
python3 scripts/check_integrity.py --all
gitleaks dir . --config .gitleaks.toml
python3 scripts/generate_sbom.py --check
python3 -m pytest -q -p no:cacheprovider

# 5. What this plan adds: the same brief, one item, analysed
curl -s -X POST http://127.0.0.1:8011/cases/1/evidence \
     -F "file=@/path/to/angel-v-murray.pdf" | python3 -m json.tool
curl -s http://127.0.0.1:8011/evidence/<id>/analysis | python3 -m json.tool
curl -s "http://127.0.0.1:8011/cases/1/search?q=Murray" | python3 -m json.tool
curl -s http://127.0.0.1:8011/cases/1/timeline | python3 -m json.tool
curl -s http://127.0.0.1:8011/evidence/<id>/custody | python3 -m json.tool

# 6. Resubmission must be a duplicate
curl -s -X POST http://127.0.0.1:8011/cases/1/evidence \
     -F "file=@/path/to/angel-v-murray.pdf" | python3 -m json.tool
#   -> "duplicate": true

# 7. Re-analysis after a lexicon change, without re-ingesting
curl -s -X POST http://127.0.0.1:8011/evidence/<id>/analyse | python3 -m json.tool
```

---

*End of plan.*
