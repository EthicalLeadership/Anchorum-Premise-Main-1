# Anchorum interface shell

This is the initial React/TypeScript shell package. It contains presentation
components only; it does not implement authentication, authorization, case
routes, evidence APIs, or domain policy.

## Local commands

```sh
npm install
npm run dev
npm run build
```

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
