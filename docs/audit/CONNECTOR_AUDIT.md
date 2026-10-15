# Connector Audit ingestion and analysis paths

**Audit id:** ANCH-2026-10-12-01
**Date:** 2026-10-12
**Branch:** `Anchorumzero_trust-on-Prem`
**Test case:** `Angel v. Murray`, 322 A.2d 630 (R.I. 1974) a contracts case brief submitted as a single PDF (`%PDF-1.7`, 149,819 bytes, SHA-256 `c58fcf248ab877e75975c04606ab60aca294c2f36d2930df858400b0b9c31830`).

## 1. Why this audit exists

The brief was to be submitted through the application as one item and analysed
across the scopes the system claims to support. Running that test case end to end
showed it cannot be done: the document never reaches the analysis stage, and once
it is made to reach it, the analysis stage has no vocabulary for it.

This audit records what was measured, what was fixed, and what remains open. It is
the companion to `docs/audit/REMEDIATION_REPORT.md`, which covers the
ANCH-2026-10-02-01 findings; this document covers the *connectors* the paths by
which a document enters the system and the paths by which it is analysed.

## 2. Method

No finding here is inferred from reading code alone. Every one was produced by
executing the path and comparing the output against the input:

1. The document was run through the GRIC inspector's document handler
   (`interface/document.py::process`) and the dossier pipeline behind it.
2. The same document was run through the product API in local mode, with the
   server started and every relevant route called over HTTP.
3. The extracted text was projected through the legal lexicon engine
   (`interface/engine.py::project_text`, `lexicons/legal-v3.1.yaml`) scope by scope.
4. The recorded payload was read back and compared against the submitted bytes by
   SHA-256 and by searching for the document's distinguishing terms.

Reproduction commands are in §12.

## 3. Summary

| id | severity | connector | state |
|----|----------|-----------|-------|
| C-1 | Critical | PDF / binary document ingestion | **Fixed** |
| C-2 | High | Legal lexicon projection (the "scopes") | **Open** |
| C-3 | High | Document classification in the dossier pipeline | **Open** |
| C-4 | High | Product API → document analysis | **Open** |
| C-5 | Medium | Custody identity of a submitted artifact | **Open** |
| C-6 | Medium | Evidence signing key is a hard prerequisite | **By design, undocumented for this path** |

One connector was missing outright and stopped the test case at the door. Four
surface as the test case is pushed through further. One is a configuration
requirement that is correct but invisible to an operator.

## 4. C-1 PDF document ingestion was not implemented (Critical, fixed)

### The contract

`GRIC_v1.0_INTERFACE_SPEC.md` §3.1 declares the `CaseSpec` evidence manifest as
accepting artifacts of type `pdf | docx | eml | image | video | json | txt`.

### The implementation

Only `.eml` was implemented. Both document entry points the GRIC inspector
(`interface/gric_server.py`) and the dossier bridge (`interface/document.py`)
routed everything else through:

```python
body = raw.decode("utf-8", errors="replace")
```

### Why that is worse than a crash

A PDF's text lives in a Flate-compressed content stream inside a binary
container. Decoding the container as UTF-8 does not fail; it succeeds and returns
mojibake. The pipeline accepted the result, classified it, committed a control
record and (with a key present) signed it. The record attested to a document
nobody had read.

Measured on the test case:

| | before | after |
|---|---|---|
| bytes in | 149,819 | 149,819 |
| characters passed to the pipeline | 142,181 | 4,845 |
| U+FFFD replacement characters | 59,630 (41.9%) | 0 |
| printable ASCII | 43.5% | |
| distinguishing terms found (of 14) | **0** | **14** |
| `Maher` | 0 | 15 |
| `Murray` | 0 | 10 |
| `Newport` | 0 | 7 |
| `consideration` | 0 | 5 |
| `$20,000` | 0 | 4 |

The 14 terms searched were: `Maher`, `Murray`, `Newport`, `consideration`,
`refuse-collection`, `contract`, `unanticipated`, `Angel`, `Rhode Island`,
`Supreme Court`, `1964`, `89D(a)`, `Restatement`, `$20,000`.

### The fix

Two new modules and a rewiring of both entry points.

`interface/pdf_text.py` a dependency-free PDF **text-layer** extractor. It
handles uncompressed and Flate-compressed content streams, literal and hex
strings, and the `Tj` / `TJ` / `'` / `"` text-showing operators, joining runs with
a kerning heuristic. It is deliberately honest about its limits: it cannot recover
text that is not there, so a scanned page raises `NoTextFound` rather than
returning an empty string. Refusing is the point an empty extraction must never
be mistaken for a document with no content.

`interface/submission.py` one place that decides what an artifact is:

- content first, then name, because a mislabelled file is a real occurrence and
  the bytes are the authority;
- PDF → parsed;
- declared text formats → decoded;
- declared binary types that are not implemented (`docx`, `odt`, images, video)
  → refused with a message naming the type, **before** any decode is attempted.

That last ordering detail is load-bearing. A `.docx` is a ZIP; long runs of a ZIP
are valid UTF-8, so a decode-first dispatch accepts it as text. That failure was
caught by the test suite written for this fix and corrected.

`interface/document.py::process` and `interface/gric_server.py::document_submit`
now call `submission` instead of decoding. The `.eml` path is untouched.

### Verified

The brief now completes the document connector end to end:

```
status        : processed
route         : quarantine_review
record_hash   : d5659d1c68da0ff59d0cab9860fbc4177e270247d6ae3aca10cde8e20a377724
payload       : body_preview = "322 A.2d 630 1974 CONTRACTS Alfred L. Angel et al.
                (plaintiffs) sued John E. Murray Jr., Newport's Director of Finance
                (defendant), and James L. Maher (defendant) over a dispute arose of
                an extra $20,000 paid for refuse-collection services due to
                unforeseen increases in housing units."
U+FFFD        : 0
```

The record now describes the document. Before the fix it described 59,630
replacement characters.

## 5. C-2 the legal lexicon projects almost nothing (High, open)

### What "analysed in all its scopes" resolves to

`interface/engine.py::project_text` splits input on blank lines and projects each
block through the CCSP engine against `lexicons/legal-v3.1.yaml` (version
`legal-v3.1`, 23 concepts, 84 patterns). The brief was split into its eight
distinct scopes and each was projected.

### The result

| scope | chars | concept_id | classification | matched concepts |
|---|---|---|---|---|
| CITATION | 29 | | `canonical_projection_fallback` | none |
| FACTS | 2,009 | `LEGAL_ALLEGATION` | `canonical_projection_insufficient` | 2 |
| PROCEDURAL_POSTURE | 188 | | `canonical_projection_fallback` | none |
| ISSUE | 218 | | `canonical_projection_fallback` | none |
| RULE | 163 | | `canonical_projection_fallback` | none |
| REASONING | 1,495 | | `canonical_projection_fallback` | none |
| HOLDING | 137 | | `canonical_projection_fallback` | none |
| DISTILLED_RULES | 599 | | `canonical_projection_fallback` | none |

Seven of eight scopes fall through to `canonical_projection_fallback` with
`concept_distribution = {}`, `unmapped = 1`, and `admissible = false`. Only the
longest block matched anything, and even that scored
`canonical_projection_insufficient` with `admissible = false`.

The whole document as a single submission behaves the same way:
`concept_id = LEGAL_ALLEGATION`, `classification = canonical_projection_insufficient`,
`admissible = false`, `forbidden = 0`, `unmapped = 0`.

### What this means

This is the connector that produces the analysis, and on a real legal document it
produces nothing. The brief is a contracts case brief offer, acceptance,
consideration, contract modification, unforeseen circumstances, the
pre-existing-duty rule, `Restatement (Second) of Contracts` and the lexicon has
no vocabulary that matches how such a document is actually written.

The failure is silent by design: `canonical_projection_fallback` is a legitimate
"no match" outcome and the model reports it as a fallback rather than an error.
An operator submitting this brief would be shown an empty projection, which reads
as "this document contains no legal concepts" rather than "the lexicon does not
cover this document's language".

### Why it was not fixed here

Unlike C-1, this cannot be corrected by repairing a connector. It is a property of
the lexicon's vocabulary and of the matcher's expectations, and it is measured
here rather than changed because:

- the lexicon is a versioned, hashed artifact (`rules_hash`, `config_hash` are
  reported in every projection and are pinned in the projection tests), so
  changing it invalidates those pins by design;
- what the concepts *should* be for contract-modification analysis is a product
  decision about the vertical's coverage, not a defect with one correct repair;
- broadening the matcher to accept this document without broadening the lexicon
  would trade a visible fallback for a silent misclassification, which is worse.

### Recommended next step

Treat "no scope matched except one" as an alertable outcome rather than a
fallback: when a submission of substantial length projects to zero concepts, the
response should say so explicitly. Separately, the lexicon needs contract-formation
and contract-modification concepts before this class of document is analysable.
Both are product decisions and are recorded here rather than made silently.

## 6. C-3 the dossier pipeline is mail-shaped (High, open)

### Observed

Every stage of the run is email semantics:

```json
{"event": "pipeline.received",   "stage": "intake", ...}
{"event": "dedup", "message_id": "<...@interface.local>", ...}
{"event": "classification", "result": "insurer", "stage": "classification", ...}
{"event": "provenance", "result": "complete", "stage": "provenance", ...}
{"event": "adapter", "result": "adapted", "stage": "adapter", ...}
{"event": "policy", "reason": "Clear path no policy constraints triggered", "result": "allowed", ...}
{"event": "control", "result": "committed", "stage": "control", ...}
```

Two problems:

1. **Classification is wrong.** A contracts case brief was classified `insurer`.
   The classifier's categories are the system's own domains; a court document is
   not one of them, so it is assigned to whatever domain scores closest. It is
   labelled confidently and with no low-confidence signal.

2. **The document has no email properties and is given email properties anyway.**
   It has a `message_id`, a `sender`, a `recipient`, a `date`, an
   `attachment_count` and a `missing_fields` list, all synthesised by the
   connector. The payload records `sender: "interface@localhost"` and
   `recipient: "user@protonmail.com"` values the connector invented and which
   now sit inside a committed, signed custody record as if they described the
   submission.

### Root cause

`dossier_pipeline/pipeline.py` exposes `process_email(bytes)`, `process_file(path)`
(for `.eml`) and `process_directory(dir)`. There is no document entry point. The
bridge in `interface/document.py` therefore synthesises an email around the
extracted text and submits that:

```python
msg["Message-ID"] = f"<{uuid.uuid4().hex}@interface.local>"
msg["Subject"] = subject
msg["From"] = sender
msg["To"] = recipient
msg.set_content(text)
```

### Consequence

`route: quarantine_review` is the honest end of this path: the pipeline cannot
classify the document and hands it to a human. That is the correct outcome, but it
is reached by way of fabricated email metadata rather than by any recognition that
this is a court filing.

### Recommended next step

Give `DossierPipeline` a document entry point that does not borrow the email
model, or record explicitly in the payload that the email fields are synthesised
and carry no evidentiary weight. The current payload does not distinguish
invented values from observed ones.

## 7. C-4 the product API never analyses evidence (High, open)

### Method

The product API was started in local mode and every route was called over HTTP
against the brief.

```
ANCHORUM_LOCAL_API_MODE=1 \
ANCHORUM_DATABASE_URL=sqlite:////tmp/casebrief/api.db \
ANCHORUM_EVIDENCE_DIRECTORY=/tmp/casebrief/api_evidence \
python3 -m uvicorn interface.server:app --host 127.0.0.1 --port 8011
```

### What works

Evidence storage is honest and byte-exact:

```
POST /cases/1/evidence        -> HTTP 201
{"id":"E-42c1d72caac341a8ab3baf87ca1a8104",
 "hash":"c58fcf248ab877e75975c04606ab60aca294c2f36d2930df858400b0b9c31830",
 "duplicate":false,"processingStatus":"stored"}

GET  /evidence/{id}/download  -> HTTP 200
stored bytes  : 149,819
stored sha256 : c58fcf248ab877e75975c04606ab60aca294c2f36d2930df858400b0b9c31830
byte-identical to the upload: True

POST /evidence/{id}/verify    -> HTTP 200
{"result":"pass","steps":[{"id":"hash","result":"pass"}]}
```

The API's `hash` **is** the submitted PDF's SHA-256, and download returns the
original bytes unchanged. Unlike the document bridge (C-5), this store binds the
artifact correctly.

### What does not work

Nothing consumes the stored evidence. The upload response says
`processingStatus: "stored"` and the evidence status stays `received`
indefinitely:

```
GET /cases/1/evidence -> [{"id":"E-...","name":"angel-v-murray.pdf",
                          "status":"received","badges":["received"]}]
GET /evidence/{id}/custody -> [{"actor":"system","action":"uploaded",
                                "chain":"not_checked"}]
```

`chain: "not_checked"` the custody chain for the evidence is not walked.

Every analysis and query surface is declared unavailable:

| route | result |
|---|---|
| `GET /cases/{id}/timeline` | 501 `FEATURE_UNAVAILABLE` `timeline` "Case chronology extraction and query are not implemented." |
| `GET /cases/{id}/search?q=` | 501 `case_search` "Case-scoped full-text search is not implemented." |
| `GET /cases/{id}/audit` | 501 `case_audit` "Case-scoped audit projections are not implemented." |
| `POST /cases/{id}/export?type=pdf` | 501 `case_export` "Case-scoped gated export generation is not implemented." |
| `POST /cases/{id}/exports/preview?type=pdf` | 501 `export_preview` "The product export gates and Barreau validation are not implemented." |
| `GET /admin/members` | 501 `member_administration` "Member management is not implemented." |

### Assessment

These are honest refusals 501 with a named feature, not a silent empty list or a
500. The API does not pretend to do work it has not done. The finding is that the
*analysis* half of the product does not exist behind this API at all, while the
analysis engine that does exist (`interface/document.py`, the dossier pipeline,
the GRIC projection) is reachable only through the GRIC inspector, not through the
product API.

So "put this file in as one item and have it analysed" is not achievable through
the product interface: the file is stored faithfully, and nothing looks at it.

### Recommended next step

Wire the upload route to the document connector that now exists
(`interface/document.py::process`, which C-1 repaired) and add the parsed text to
the evidence record, so `processingStatus` can advance past `"stored"`. Until
that happens, `timeline` and `case_search` have nothing to search.

## 8. C-5 custody does not bind the submitted artifact (Medium, open)

### Observed

Two separate runs of the same PDF through `interface/document.py::process`
produced two different `raw_sha256` values:

```
run 1: raw_sha256 = 2232297fbe9cbd16a54ca09e707b61d7e5c7c8f82311c4df0bc3f659bb1ae7a2
run 2: raw_sha256 = 9d4a2d4802f0152e560db215ee44786f9652c82c2fdf9c648acc613472a1daad
submitted PDF    = c58fcf248ab877e75975c04606ab60aca294c2f36d2930df858400b0b9c31830
```

### Root cause

`raw_sha256` is taken over the synthetic `.eml` that
`interface/document.py::_wrap_text_as_eml` builds, and that wrapper contains a
`uuid4()` Message-ID and a wall-clock `Date`. The recorded hash is therefore a
function of when the ingestion ran, not of what was ingested.

### Why this matters

- **Not reproducible.** The same document ingested twice yields two different
  "raw" hashes. A custody record whose identity changes per run cannot be used to
  demonstrate that a particular document was the one received.
- **Not bound to the artifact.** Nothing in the committed payload carries the PDF's
  own SHA-256 (`c58fcf24…`). The payload records the hash of a wrapper the system
  generated. The product API's evidence store does carry the true artifact hash
  (C-4), so the two halves of the system disagree about what "the artifact hash"
  means.
- **Dedup never fires.** The pipeline dedups on `message_id`; a fresh UUID every
  time means a genuine resubmission is always treated as new. Both observed runs
  reported `"result": "claimed"`.

### Not fixed here

Making `raw_sha256` a function of the submission requires deciding what the record
should bind to the derived text, the original artifact, or both and that
changes what a signed custody record attests to. That is the owner's decision, not
a connector defect with one implementation. The two candidate repairs are:

1. carry the submitted artifact's SHA-256 into the record alongside the wrapper
   hash, so both are present and distinguishable; or
2. derive the synthetic `Message-ID` (and pin the synthetic `Date`) from the
   content, making `raw_sha256` deterministic which also restores dedup.

Option 2 is contained within the connector and needs no schema change, but it
changes dedup semantics, so it is recorded rather than applied.

## 9. C-6 the evidence signing key is a hard prerequisite (by design)

### Observed

Without `GDC_EVIDENCE_SECRET`, the document connector does not complete:

```
status      : failed_runtime
route       :
reason      : No evidence signing secret available. Set GDC_EVIDENCE_SECRET (or
              pass an explicit secret). Refusing to sign evidence with an empty
              key, because those signatures are forgeable by anyone.
```

With the key set, the same input completes:

```
status      : processed
route       : quarantine_review
record_hash : d5659d1c68da0ff59d0cab9860fbc4177e270247d6ae3aca10cde8e20a377724
```

### Assessment

This is the intended fail-closed behaviour from the ANCH-2026-10-02-01 remediation
(F-02): refusing to sign with no key is correct, and the error message names the
variable and the reason. It is listed here not as a defect but because an operator
running the document path for the first time will hit it, and the message is the
only place that requirement is stated. It is not documented in the interface
README's local-run recipe.

## 10. What changed in this pass

| file | change |
|---|---|
| `interface/pdf_text.py` | new dependency-free PDF text-layer extractor |
| `interface/submission.py` | new single artifact-type dispatcher for both entry points |
| `interface/document.py` | dispatch by artifact type; PDFs parsed rather than decoded |
| `interface/gric_server.py` | same, via `interface/submission` |
| `tests/test_pdf_text.py` | new 26 pins |

`tests/test_pdf_text.py` pins the defect rather than only the fix: it asserts that
decoding a synthetic PDF as UTF-8 loses its text, and that the extractor then
finds it. That is a test that fails if the decode-everything behaviour returns.

Also pinned: refused binary types, refusal-before-decode ordering, `NoTextFound`
for a document with no text layer, escaped parentheses, hex strings, kerning word
gaps, and guarded by a file-existence check so it does not fail on a machine
without the sample the real brief's distinguishing terms and a zero U+FFFD
count.

## 11. Gates

| gate | result |
|---|---|
| `scripts/check_integrity.py --selftest` | 6/6 |
| `scripts/check_integrity.py --all` | OK |
| `gitleaks dir .` | no leaks found |
| `scripts/generate_sbom.py --check` | SBOM matches `requirements.lock` |
| `pytest`, commit `0e9c273` | **354 passed** |
| `pytest`, working tree | **362 passed** |
| `pytest tests/test_pdf_text.py` | 26 passed |

Both figures are given because they are different claims. The working tree carries
uncommitted work from a concurrent actor a modified front end and an untracked
`tests/test_interface_api.py` and those 8 tests account for the difference. Only
the committed figure travels with a clone; it was re-run in a detached worktree of
`0e9c273`, untouched by the concurrent edits, where the integrity gate, secret
scan and SBOM check also pass.

Before this pass the committed tree ran 328 tests, so the change is +26, matching
the new pins in `tests/test_pdf_text.py`.

## 12. Reproduction

```bash
# 1. The extractor against the brief
python3 /tmp/probe_final.py            # section A/B prints the before/after counts

# 2. The document connector end to end
ANCHORUM_ENV=local OUTPUT_DIR=/tmp/casebrief/out \
GDC_CONTROL_SIGNING_KEY="<32+ chars>" \
GDC_EVIDENCE_SECRET="<32+ chars>" \
python3 /tmp/probe_payload.py          # prints the committed payload's text

# 3. The product API
ANCHORUM_LOCAL_API_MODE=1 \
ANCHORUM_DATABASE_URL=sqlite:////tmp/casebrief/api.db \
ANCHORUM_EVIDENCE_DIRECTORY=/tmp/casebrief/api_evidence \
python3 -m uvicorn interface.server:app --host 127.0.0.1 --port 8011
python3 /tmp/api_probe.py              # exercises every route in section 7

# 4. The gates
python3 -m pytest -q
```

The probe scripts are throwaway and are not committed; §11's gate results are
reproducible from the committed tree alone.

## 13. Status

**Fixed:** 1 (C-1). **Open:** 4 (C-2, C-3, C-4, C-5). **By design:** 1 (C-6).

The stated goal was that the brief could be put in as one item and analysed in all
its scopes. After this pass the brief can be put in, and the result describes the
brief rather than describing mojibake. It is not yet analysed in its scopes: C-4
means the product API does not analyse it at all, and C-2 means the engine that
would do the analysing has no vocabulary for it.

Those two are the remaining blockers to the original request, and neither is a
connector that can be repaired in isolation C-4 needs the analysis path wired
into the API, and C-2 needs the lexicon extended for contract and case-brief
language. Both are recorded here with the evidence needed to decide them rather
than changed silently.
