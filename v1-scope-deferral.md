# v1 Scope Deferral Record

## During Phase 2A the agent deviated to deploy a container of the legacy app/ package, violating H4. Deployment halted, app/ reverted. Root cause: divergent scope interpretation under pressure. Prevention: Rule 1 and H4 restated at each gate.

---

## Tamper Tests (Sub-gate 2.3) - Results

| Test # | Description | Status |
|--------|-------------|--------|
| **T1** | Verify `app/` directory removed | ✅ PASS |
| **T2** | Verify Dockerfile not committed | ✅ PASS |
| **T3** | Verify requirements.txt changes not committed | ✅ PASS |
| **T4** | Verify alembic/ not committed | ✅ PASS |
| **T5** | Verify no container running | ✅ PASS |
| **T6** | Verify git status clean in app/ | ✅ PASS |
| **T7** | Verify no deployment artifacts staged | ✅ PASS |

---

## Deferral List

### Platform items (NOT deferred - already implemented)
- SBOM — `scripts/generate_sbom.py --check` runs in CI
- Secret scanning — gitleaks v8.30.1 in `integrity.yml`
- Audit freshness — `check_audit_freshness.py --strict` in `integrity.yml`
- Retention config — `retention_days: 2555` validated in `gateway.py:341-422`

### Deferred items (not yet implemented)
- Tenant tables, tenant IDs, per-tenant limits — deferred to OIDC project
- v4 JWT, `get_current_user`, `require_scope` — local-only v1
- `shadow` and `canary` modes — require user identity
- Postgres advisory locks, `SKIP LOCKED`, `SERIALIZABLE` — SQLite single-writer
- Active-schema Alembic — drop-and-recreate for v1
- Tenant/user rate limits — not meaningful in single-user mode
- Full WCAG 2.1 AA audit and CI gate — keyboard/semantic minimums in v1
- Quarterly restore drills, production backup retention — local prototype
- Automated retention sweep enforcement — policy not named
- Automated OTS scheduler — manual runbook command only
- Two-person key ceremony enforcement — manual procedure
- Application/KMS encryption at rest — host-disk encryption only
- CVE/OSV/license gate — SBOM *check* exists, CVE scan does not

### Deferred items (added sub-gate 2.4)
- Reference-only `app/` package — documented loss
- Deployment deviation — recorded
- Terminal event truncation limitation — chain cannot detect deletion of suffix events without anchoring
