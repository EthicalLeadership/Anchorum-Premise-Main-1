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
rather than decoded as text — decoding binary as text succeeds wrongly and puts
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
whose chain is explicitly marked unchecked; this does not provide immutable
storage, cryptographic custody guarantees, malware scanning, or indexing.
Timeline, search, exports, and member administration remain unavailable and
return a named `FEATURE_UNAVAILABLE` response.

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
