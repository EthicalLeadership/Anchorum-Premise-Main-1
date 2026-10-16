# Anchorum interface shell

This package contains the Anchorum Prem Main React/TypeScript shell and its
FastAPI entry point. The API currently provides a local/test session,
SQLite-backed case operations, and local evidence upload/list/download with
SHA-256 read-back verification.

## Local commands

```sh
npm install
npm run dev
npm run build
```

## Local API hookup (development/test only)

Run the API on loopback with the local/test mode explicitly enabled:

```sh
ANCHORUM_LOCAL_API_MODE=1 \
ANCHORUM_DATABASE_URL=sqlite:///./output/anchorum-local.db \
uvicorn interface.server:app --host 127.0.0.1 --port 8000
```

The document handler at `POST /document` runs the full dossier pipeline, which
**signs** the control record and the evidence. It therefore fails closed without
signing material, and the failure is by design rather than a configuration bug:

```sh
export GDC_CONTROL_SIGNING_KEY="<at least 32 characters>"
export GDC_EVIDENCE_SECRET="<at least 32 characters>"
```

With neither set, a submission returns `status: failed_runtime` with the reason
`No evidence signing secret available. Set GDC_EVIDENCE_SECRET (or pass an
explicit secret). Refusing to sign evidence with an empty key, because those
signatures are forgeable by anyone.` A short secret is refused as well, not
stretched.

Accepted artifact types: `.eml` (the native path), `.pdf` (text layer extracted),
and the plain-text formats `.txt .md .json .csv .xml .html .yaml .log .rst .ini
.cfg .toml`. Binary types named in the GRIC manifest but not implemented
(`docx`, `odt`, images, video) are **refused with a message naming the type**
rather than decoded as text decoding binary as text succeeds wrongly and puts
the result into a signed record. A PDF with no text layer (a scan) is refused for
the same reason.

In a second terminal, start the Vite UI against that API:

```sh
cd interface
VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

Open the UI at `http://127.0.0.1:8000/#/cases` when serving the built shell,
or `http://localhost:5173/#/cases` when using Vite. The `#/` fragment is
required: plain `/cases/...` paths are API endpoints, not UI navigation.

The local API mode supplies a configured local session; it does not authenticate
users or enforce tenant/case authorization. Do not expose it to a network or
use it for production data. Leave `VITE_API_BASE_URL` unset to use the UI's
fixture adapter. `ANCHORUM_LOCAL_USER_NAME`, `ANCHORUM_LOCAL_USER_ID`, and
`ANCHORUM_LOCAL_ROLE` can set the local identity, and
`ANCHORUM_LOCAL_CORS_ORIGINS` can set comma-separated development origins.

`GET /health` checks database connectivity. Case data and evidence metadata are
stored in SQLite; original evidence files are stored under `output/evidence`
(override with `ANCHORUM_EVIDENCE_DIRECTORY`). Evidence verification checks the
stored bytes against their SHA-256 digest. Custody events are local audit rows
whose chain is explicitly marked unchecked, and each entry carries a
`chainDetail` that says so; this does not provide immutable storage,
cryptographic custody guarantees, malware scanning, or indexing.

### Reading an artifact

Reading a stored artifact is separate from committing one, and the two tiers have
different requirements.

**Reading needs no signing material.** `GET /evidence/{id}/analysis` extracts the
text, splits it into its IRAC scopes and projects each scope through the lexicon.
That path is pure and deterministic, so it runs on a host with no keys
configured. `POST /evidence/{id}/analyse` re-runs it on demand, which is what a
lexicon change needs: re-uploading evidence to re-analyse it would destroy the
meaning of its custody chain. Re-analysis is idempotent and records
`analysedAt` each time.

**Committing still requires keys** and still fails closed, as above.

The extracted text is written beside the stored bytes as `<storage_key>.txt` and
never into the database or the analysis record, so search has something to search
without case content riding along in an export. Extraction is bounded at 25 MB:
above that ceiling the analysis is recorded as `skipped_oversize` rather than
attempted, because extraction runs synchronously inside the upload request, and an
unbounded parse of a hostile upload is a denial of service on a single-process
local API.

The analysis record reports, per scope, the concepts that matched or an explicit
statement that the lexicon covered nothing there, plus a `coverage` block. That
block is the point: the engine reporting `canonical_projection_fallback` means "no
match", which is a legitimate outcome, and without the coverage summary seven
empty scopes read as "this document contains no legal concepts". A document whose
language the lexicon does not cover says so instead.

What this is **not**: it describes the document's language. It is not a statement
that the evidence is authentic, admissible or unaltered, and it is not malware
scanning. It reports what the lexicon matched; a reviewer decides what that means.

`GET /cases/{id}/search?q=` and `GET /cases/{id}/timeline` are implemented over
that stored text and the API's own audit rows. Search returns a bare array of
`{id, excerpt}` and reports which matcher ran in the `X-Anchorum-Search-Method`
response header, because substring matching is not token matching and the
difference has to stay visible. The timeline is an allowlist of the case's own
events (`case_created`, `evidence_uploaded`, `evidence_verified`,
`evidence_analysed`); chronology extracted from a document's *content* is a
different feature and is not provided. Exports and member administration remain
unavailable and return a named `FEATURE_UNAVAILABLE` response.

`AppShell` accepts a typed bootstrap object and route builders. A FastAPI
application can supply those values through its page bootstrap or a versioned
JSON endpoint. The server remains responsible for authentication, authorization,
CSRF protection, audit writes, and every mutation. Hidden navigation is not an
access-control boundary.

English and French interface copy lives in `locales/en.json` and
`locales/fr.json`. The translation adapter validates interpolation parameters,
and the test suite checks catalog key parity, duplicate keys, interpolation
placeholder parity, and complete values. Dynamic UI tokens are leaf values
(for example, `uploaded` or `linked`); components add their catalog namespace.
Case timestamps are formatted using the case's configured timezone.

The bootstrap contract carries only UI-facing identity and status data.
Verification callbacks should return user-safe outcomes; the shell presents a
generic localized failure rather than exposing raw server exception details.

The current `App` intentionally renders the no-case-selected state. Case data,
review fixtures, and API wiring are separate follow-up work.

## Scripts

[`scripts/fr-review.js`](./scripts/fr-review.js) generates the French catalog
review sheet. Do not regenerate while a review is in flight; pass `--force`
only after the review has come back. The script supports `--priority-only` for
the priority section.

COUNSEL palette integration is described in
[`docs/THEME_EXTENSIONS.md`](./docs/THEME_EXTENSIONS.md). Neutral system-color
fallbacks are for development preview only.
