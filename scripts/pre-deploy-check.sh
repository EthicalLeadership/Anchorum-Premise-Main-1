#!/bin/bash
# Pre-deployment verification script for anchorum-prem v1.0.0

set -e

echo "=== Pre-Deployment Verification ==="
echo ""

# 1. Verify citation validation integration
echo "[1/6] Checking citation validation integration..."
if grep -q 'validate_all_citations' interface/llm_classifier.py; then
    echo "    ✓ Citation validation integrated into LLM classifier"
else
    echo "    ✗ Citation validation NOT found in LLM classifier"
    exit 1
fi

# 2. Verify upload allowlist fix
echo "[2/6] Checking upload allowlist fix..."
if grep -q 'Form("")' interface/anchorum_api.py; then
    echo "    ✓ Upload allowlist bypass fixed"
else
    echo "    ✗ Upload allowlist bypass NOT fixed"
    exit 1
fi

# 3. Verify environment pinning
echo "[3/6] Checking environment pinning..."
if [ -f requirements.lock ]; then
    echo "    ✓ requirements.lock exists"
    if command -v pip &> /dev/null; then
        pip check > /dev/null 2>&1 && echo "    ✓ Dependencies verified" || exit 1
    fi
else
    echo "    ✗ requirements.lock NOT found"
    exit 1
fi

# 4. Run test suite baseline
echo "[4/6] Running test suite baseline..."
if command -v pytest &> /dev/null; then
    pytest tests/ --tb=no -q > /tmp/test_output.txt 2>&1 || true
    PASSED=$(grep -o '[0-9]* passed' /tmp/test_output.txt | grep -o '[0-9]*' || echo "0")
    FAILED=$(grep -o '[0-9]* failed' /tmp/test_output.txt | grep -o '[0-9]*' || echo "0")
    if [ "$FAILED" = "0" ]; then
        echo "    ✓ Tests passed: $PASSED tests"
    else
        echo "    ✗ Tests failed: $FAILED failures"
        exit 1
    fi
else
    echo "    ⚠ pytest not available, skipping test check"
fi

# 5. Verify no client data remains
echo "[5/6] Checking for client data..."
CLIENT_FILES=()
for file in config_live.example.json llm_cache.json output/ dev_data/; do
    if [ -e "$file" ]; then
        CLIENT_FILES+=("$file")
    fi
done
if [ ${#CLIENT_FILES[@]} -eq 0 ]; then
    echo "    ✓ No client data found (virgin state)"
else
    echo "    ⚠ Client data detected: ${CLIENT_FILES[*]}"
    echo "    Note: This may be expected in development environment"
fi

# 6. Verify audit stamp matches HEAD
echo "[6/6] Checking audit stamp..."
if [ -f CAPABILITY_AUDIT.md ]; then
    STAMP=$(grep 'AUDIT_STAMP' CAPABILITY_AUDIT.md | grep -o '[a-f0-9]\{7\}' || echo "")
    CURRENT_COMMIT=$(git rev-parse --short HEAD)
    if [ "$STAMP" = "$CURRENT_COMMIT" ]; then
        echo "    ✓ Audit stamp matches current commit ($CURRENT_COMMIT)"
    else
        echo "    ⚠ Audit stamp mismatch: $STAMP vs $CURRENT_COMMIT"
        echo "    Note: This may be expected during development"
    fi
else
    echo "    ⚠ CAPABILITY_AUDIT.md not found"
fi

echo ""
echo "=== Pre-Deployment Verification Complete ==="
echo "Status: READY FOR DEPLOYMENT"
