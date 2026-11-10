#!/usr/bin/env python3
"""
Generate audit stamp from the tree.

This script generates:
- Route counts (from app/routes and dossier_pipeline)
- Test counts (from tests/)
- File counts (tracked files)
- Audit stamp (commit SHA of last clean state)

Usage:
    python scripts/generate_audit_stamp.py [--output FILE]
"""

import os
import sys
import json
import hashlib
from pathlib import Path


def count_python_files(root: str, exclude_dirs: list[str]) -> int:
    """Count Python files excluding specified directories."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # Filter out excluded directories
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        for filename in filenames:
            if filename.endswith('.py') and not filename.startswith('__'):
                count += 1
    return count


def count_test_files(root: str) -> int:
    """Count test files (test_*.py or *_test.py)."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        for filename in filenames:
            if filename.startswith('test_') or filename.endswith('_test.py'):
                count += 1
    return count


def count_routes(root: str) -> int:
    """Count route files in app/routes and dossier_pipeline."""
    count = 0
    # Check app/routes
    routes_path = os.path.join(root, 'app', 'routes')
    if os.path.isdir(routes_path):
        for filename in os.listdir(routes_path):
            if filename.endswith('.py'):
                count += 1
    
    # Check dossier_pipeline for gateway/route files
    pipeline_path = os.path.join(root, 'dossier_pipeline')
    if os.path.isdir(pipeline_path):
        for filename in os.listdir(pipeline_path):
            if 'gateway' in filename.lower() or 'route' in filename.lower():
                count += 1
    
    return count


def generate_tree_hash(root: str) -> str:
    """Generate a hash of the current tree state."""
    hasher = hashlib.sha256()
    
    # Walk through tracked files
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip common exclude directories
        if any(part in dirpath for part in ['.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache']):
            continue
        
        for filename in sorted(filenames):
            filepath = os.path.join(dirpath, filename)
            try:
                with open(filepath, 'rb') as f:
                    # Read file content in chunks
                    content = f.read()
                    hasher.update(content[:1024])  # Hash first 1KB for speed
            except (IOError, OSError):
                continue
    
    return hasher.hexdigest()[:12]


def get_git_commit_sha(root: str) -> str | None:
    """Get the current HEAD commit SHA."""
    import subprocess
    try:
        result = subprocess.run(
            ['git', '-C', root, 'rev-parse', 'HEAD'],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def generate_audit_report(root: str, output_file: str | None = None) -> dict:
    """Generate the audit report."""
    
    # Get current commit
    commit_sha = get_git_commit_sha(root)
    
    # Count files
    all_py_files = count_python_files(root, ['.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache'])
    test_files = count_test_files(os.path.join(root, 'tests'))
    route_files = count_routes(root)
    
    # Generate tree hash
    tree_hash = generate_tree_hash(root)
    
    report = {
        'commit_sha': commit_sha or 'unknown',
        'tree_hash': tree_hash,
        'file_counts': {
            'total_python_files': all_py_files,
            'test_files': test_files,
            'route_files': route_files
        },
        'audit_stamp': f"{commit_sha[:7]}-{tree_hash}" if commit_sha else 'unknown-unknown'
    }
    
    # Output to file if specified
    if output_file:
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"Audit report written to {output_file}")
    
    return report


def main():
    """Main entry point."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Default output file
    output_file = os.path.join(root, 'docs', 'audit', 'AUDIT_STAMP.json')
    
    # Check for --output argument (skip first arg which is script name)
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
    
    report = generate_audit_report(root, output_file)
    
    # Print summary
    print("=" * 60)
    print("AUDIT STAMP GENERATION REPORT")
    print("=" * 60)
    print(f"Commit SHA: {report['commit_sha']}")
    print(f"Tree Hash: {report['tree_hash']}")
    print(f"Audit Stamp: {report['audit_stamp']}")
    print("-" * 60)
    print("File Counts:")
    print(f"  Total Python files: {report['file_counts']['total_python_files']}")
    print(f"  Test files: {report['file_counts']['test_files']}")
    print(f"  Route files: {report['file_counts']['route_files']}")
    print("=" * 60)
    
    return report


if __name__ == '__main__':
    main()
