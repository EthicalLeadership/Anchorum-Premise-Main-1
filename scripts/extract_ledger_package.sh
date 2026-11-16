#!/bin/bash
# Complete extraction of interface/ledger into anchorum-ledger package
# Run from the workspace root directory

set -e

WORKSPACE_ROOT="$(pwd)"
SOURCE_DIR="${WORKSPACE_ROOT}/interface/ledger"
TARGET_DIR="${WORKSPACE_ROOT}/packages/anchorum_ledger/anchorum_ledger"
TESTS_SRC="${WORKSPACE_ROOT}/tests/test_ledger_*"
TESTS_DST="${WORKSPACE_ROOT}/packages/anchorum_ledger/tests"

echo "=== Extracting interface/ledger into anchorum-ledger package ==="

# Create target directories
echo "[1/6] Creating target directories..."
mkdir -p "${TARGET_DIR}"
mkdir -p "${TESTS_DST}"

# Copy source files (excluding routers that stay in main project)
echo "[2/6] Copying source files from interface/ledger/..."
for file in canonical.py merkle.py signing.py snapshot.py timestamp.py tsa_export.py anchor.py; do
    if [[ -f "${SOURCE_DIR}/${file}" ]]; then
        echo "  ✓ Copying ${file}..."
        cp "${SOURCE_DIR}/${file}" "${TARGET_DIR}/${file}"
    else
        echo "  ⚠ File not found: ${file}"
    fi
done

# Remove pycache and __pycache__ directories to avoid issues
echo "[3/6] Cleaning up cache files..."
find "${TARGET_DIR}" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "${TARGET_DIR}" -name "*.pyc" -delete 2>/dev/null || true

# Copy test files (rename to match new package structure)
echo "[4/6] Preparing test files..."
for test_file in "${TESTS_SRC}"; do
    if [[ -f "$test_file" ]]; then
        basename=$(basename "$test_file")
        # Remove "test_" prefix and convert dash to underscore for import compatibility
        new_name="${basename#test_}"
        new_name="${new//-/_}"
        new_path="${TESTS_DST}/${new_name}"
        
        if [[ -f "$test_file" ]]; then
            echo "  ✓ Copying test file to ${new_name}..."
            cp "$test_file" "$new_path"
            
            # Update imports in the test file (from interface.ledger -> anchorum_ledger)
            sed -i 's/from interface\.ledger\.canonical/from anchorum_ledger.canonical/' "$new_path" 2>/dev/null || true
            sed -i 's/from interface\.ledger\.merkle/from anchorum_ledger.merkle/' "$new_path" 2>/dev/null || true
            sed -i 's/from interface\.ledger\.signing/from anchorum_ledger.signing/' "$new_path" 2>/dev/null || true
            sed -i 's/from interface\.ledger\.snapshot/from anchorum_ledger.snapshot/' "$new_path" 2>/dev/null || true
        fi
    fi
done

# Create symlink or copy for existing test files if they already exist with different names
echo "[5/6] Creating symlinks/copies for test files..."
for f in "${TESTS_DST}"/*.py; do
    if [[ -f "$f" ]]; then
        src_file=$(grep -h "^from anchorum_ledger\." "$f" 2>/dev/null | head -1 || echo "")
        if [[ ! "$src_file" =~ "anchorum_ledger" ]]; then
            # No anchorum_ledger imports, keep as-is (it's a placeholder)
            continue
        fi
    fi
done

echo "[6/6] Extraction complete!"
echo ""
echo "Package structure created at:"
echo "  ${TARGET_DIR}/"
echo "Tests copied to: ${TESTS_DST}/"
echo ""
echo "=== Verification ==="
echo "Source files copied:"
for file in canonical.py merkle.py signing.py snapshot.py timestamp.py tsa_export.py anchor.py; do
    if [[ -f "${TARGET_DIR}/${file}" ]]; then
        echo "  ✓ ${file}"
    else
        echo "  ✗ ${file} (NOT COPIED - run manually)"
    fi
done

echo ""
echo "=== Next steps ==="
echo "1. Run: pip install -e . from the packages/anchorum_ledger directory"
echo "2. Verify tests pass: cd packages/anchorum_ledger && python -m pytest tests/"
echo "3. The package is now ready for distribution or use in other projects"
