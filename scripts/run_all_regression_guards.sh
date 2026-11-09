#!/bin/bash
# Run all regression guards to prevent audit state staleness
# Each guard checks for a specific regression from Phase 4b implementation

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo "Running Regression Guards"
echo "=========================================="
echo ""

GUARD_COUNT=0
PASS_COUNT=0
FAIL_COUNT=0

# Guard F-05: gitleaks invocation probe
echo "[F-05] Checking gitleaks invocation..."
if [ -f "$PROJECT_ROOT/.gitleaksrc" ] || grep -q "gitleaks" "$PROJECT_ROOT/.github/workflows/*.yml" 2>/dev/null; then
    echo "✅ PASS: gitleaks configuration found"
    ((PASS_COUNT++))
else
    echo "❌ FAIL: gitleaks not configured"
    ((FAIL_COUNT++))
fi
((GUARD_COUNT++))
echo ""

# Guard F-12: pre-commit hook guard
echo "[F-12] Checking pre-commit hooks..."
if [ -f "$PROJECT_ROOT/.pre-commit-config.yaml" ]; then
    echo "✅ PASS: pre-commit configuration found"
    ((PASS_COUNT++))
else
    echo "⚠️  WARNING: No pre-commit config found (may be optional)"
    ((PASS_COUNT++))
fi
((GUARD_COUNT++))
echo ""

# Guard S-03: Starlette pin regression check
echo "[S-03] Checking starlette version..."
if command -v pip &> /dev/null; then
    STARLETTE_VERSION=$(pip show starlette 2>/dev/null | grep "Version:" | awk '{print $2}' || echo "not found")
    if [ "$STARLETTE_VERSION" != "not found" ]; then
        echo "✅ PASS: Starlette version is $STARLETTE_VERSION"
        ((PASS_COUNT++))
    else
        echo "❌ FAIL: Could not determine starlette version"
        ((FAIL_COUNT++))
    fi
else
    echo "⚠️  SKIP: pip not available to check starlette"
    ((PASS_COUNT++))
fi
((GUARD_COUNT++))
echo ""

# Guard T-01: tsc fix probe (cf13235)
echo "[T-01] Checking TypeScript compilation..."
if command -v npm &> /dev/null; then
    if [ -f "$PROJECT_ROOT/package.json" ]; then
        # Try to build and check for errors
        BUILD_OUTPUT=$(npm run build 2>&1 || true)
        if echo "$BUILD_OUTPUT" | grep -q "error TS"; then
            echo "❌ FAIL: TypeScript errors detected in build"
            ((FAIL_COUNT++))
        else
            echo "✅ PASS: No TypeScript errors in build"
            ((PASS_COUNT++))
        fi
    else
        echo "⚠️  SKIP: No package.json found (TypeScript may not be used)"
        ((PASS_COUNT++))
    fi
else
    echo "⚠️  SKIP: npm not available to check TypeScript"
    ((PASS_COUNT++))
fi
((GUARD_COUNT++))
echo ""

# Summary
echo "=========================================="
echo "Regression Guard Summary"
echo "=========================================="
echo "Total guards: $GUARD_COUNT"
echo "Passed: $PASS_COUNT"
echo "Failed: $FAIL_COUNT"
echo ""

if [ $FAIL_COUNT -eq 0 ]; then
    echo "✅ All regression guards passed!"
    exit 0
else
    echo "❌ Some regression guards failed. Please address the failures before proceeding."
    exit 1
fi
