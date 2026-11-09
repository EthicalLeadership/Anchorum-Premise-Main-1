# Regression Guards

This document tracks regression guards to prevent future staleness of the audit state. Each guard corresponds to a specific fix or improvement that was tracked during Phase 4b implementation.

## Guard Registry

| ID | Name | Description | Command | Status |
|---|---|---|---|---|
| F-05 | gitleaks invocation probe | Verify gitleaks is invoked correctly in CI/CD pipeline | `./scripts/check_gitleaks_invocation.sh` | ✅ Active |
| F-12 | pre-commit hook guard | Ensure pre-commit hooks are properly configured and running | `git commit --no-pager` (triggers hooks) | ✅ Active |
| S-03 | Starlette pin regression check | Verify starlette version is pinned to prevent incompatibilities | `pip show starlette && python -c "import starlette; print(starlette.__version__)"` | ✅ Active |
| T-01 | tsc fix probe | Validate TypeScript compilation fixes (cf13235) are maintained | `npm run build 2>&1 \| grep -q 'error TS' && echo 'FAIL: TypeScript errors detected'` | ✅ Active |

## Guard Commands

### F-05: gitleaks invocation probe

```bash
./scripts/check_gitleaks_invocation.sh
```

**Purpose:** Verifies that gitleaks is properly invoked in the CI/CD pipeline to detect secrets in commits.

**Expected output:**
- ✅ PASS: gitleaks configuration found and active
- ❌ FAIL: gitleaks not configured or missing from pipeline

### F-12: pre-commit hook guard

```bash
git commit --no-pager -m "test message"
```

**Purpose:** Triggers pre-commit hooks to validate code quality, linting, and security checks before allowing commits.

**Expected behavior:**
- Hooks run automatically on `git commit`
- Fails if secrets detected (via gitleaks)
- Fails if linting errors present

### S-03: Starlette pin regression check

```bash
pip show starlette && python -c "import starlette; print(f'Starlette version: {starlette.__version__}')"
```

**Purpose:** Ensures starlette is pinned to a compatible version to prevent runtime incompatibilities.

**Expected output:**
- Starlette version should match the pinned version in `pyproject.toml` or `requirements.txt`
- Any version mismatch indicates a potential regression

### T-01: tsc fix probe (cf13235)

```bash
npm run build 2>&1 | grep -q 'error TS' && echo "FAIL: TypeScript errors detected" || echo "PASS: No TypeScript errors"
```

**Purpose:** Validates that TypeScript compilation fixes from commit cf13235 are maintained.

**Expected output:**
- ✅ PASS: Build succeeds without TypeScript errors
- ❌ FAIL: TypeScript errors detected (indicates regression)

## Running All Guards

To run all regression guards in a single command:

```bash
./scripts/run_all_regression_guards.sh
```

This script executes each guard and reports the overall status.

## Adding New Guards

When a new fix or improvement is made, add a corresponding guard to this registry:

1. **Define the guard** - Create a test/command that detects regressions
2. **Add to table** - Register in the Guard Registry section
3. **Add command** - Include the verification command
4. **Update scripts** - Add to `run_all_regression_guards.sh` if applicable

## Audit State Protection

These guards collectively protect the audit state by:
- Preventing secret leaks (F-05)
- Ensuring code quality gates (F-12)
- Maintaining dependency compatibility (S-03)
- Preserving TypeScript fixes (T-01)

Any failure in these guards indicates a potential regression that should be addressed before proceeding with further development.
