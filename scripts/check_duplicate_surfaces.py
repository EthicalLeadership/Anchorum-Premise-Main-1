#!/usr/bin/env python3
"""
Check for duplicate/unreferenced surfaces in the codebase.

This script identifies:
- mail_intake_pipeline_dossier fork (should be removed if unreferenced)
- backend/ directory (should be removed if unreferenced)
- .bak-* files (backup files to clean up)
"""

import os
import sys
from pathlib import Path


def find_python_imports(root: str) -> dict:
    """Find all Python imports in the codebase."""
    imports = {
        'dossier_pipeline': 0,
        'backend': 0,
        'mail_intake_pipeline_dossier': 0,
    }
    
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip virtual environments and node_modules
        if any(part in dirpath for part in ['.venv', 'node_modules', '.git']):
            continue
        
        for filename in filenames:
            if not filename.endswith('.py'):
                continue
            
            filepath = os.path.join(dirpath, filename)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                    # Check for imports
                    if 'dossier_pipeline' in content:
                        imports['dossier_pipeline'] += content.count('dossier_pipeline')
                    if 'from backend' in content or 'import backend' in content:
                        imports['backend'] += 1
                    if 'mail_intake_pipeline_dossier' in content:
                        imports['mail_intake_pipeline_dossier'] += 1
                        
            except (IOError, OSError):
                continue
    
    return imports


def find_backup_files(root: str) -> list:
    """Find backup files (.bak-*, ~, etc.)."""
    backup_files = []
    
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip virtual environments and node_modules
        if any(part in dirpath for part in ['.venv', 'node_modules', '.git']):
            continue
        
        for filename in filenames:
            if filename.endswith('.bak') or filename.endswith('.bak-') or filename.endswith('~'):
                backup_files.append(os.path.join(dirpath, filename))
    
    return backup_files


def check_directory_unreferenced(root: str, dir_name: str) -> bool:
    """Check if a directory is unreferenced in the codebase."""
    imports = find_python_imports(root)
    count = imports.get(dir_name, 0)
    
    # Also check for direct imports or from statements
    import_pattern = f'from {dir_name} '
    from_count = 0
    
    for dirpath, dirnames, filenames in os.walk(root):
        if any(part in dirpath for part in ['.venv', 'node_modules', '.git']):
            continue
        
        for filename in filenames:
            if not filename.endswith('.py'):
                continue
            
            filepath = os.path.join(dirpath, filename)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    if import_pattern in content:
                        from_count += 1
            except (IOError, OSError):
                continue
    
    return count == 0 and from_count == 0


def main():
    """Main entry point."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    print("=" * 70)
    print("DUPLICATE SURFACES CHECK")
    print("=" * 70)
    print()
    
    # Check dossier_pipeline references
    imports = find_python_imports(root)
    print(f"dossier_pipeline references: {imports['dossier_pipeline']}")
    
    # Check backend references
    backend_count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if any(part in dirpath for part in ['.venv', 'node_modules', '.git']):
            continue
        
        for filename in filenames:
            if not filename.endswith('.py'):
                continue
            
            filepath = os.path.join(dirpath, filename)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    if 'from backend' in content or 'import backend' in content:
                        backend_count += 1
            except (IOError, OSError):
                continue
    
    print(f"backend references: {backend_count}")
    
    # Check mail_intake_pipeline_dossier references
    mail_count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if any(part in dirpath for part in ['.venv', 'node_modules', '.git']):
            continue
        
        for filename in filenames:
            if not filename.endswith('.py'):
                continue
            
            filepath = os.path.join(dirpath, filename)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    if 'mail_intake_pipeline_dossier' in content:
                        mail_count += 1
            except (IOError, OSError):
                continue
    
    print(f"mail_intake_pipeline_dossier references: {mail_count}")
    
    # Find backup files
    backup_files = find_backup_files(root)
    print(f"Backup files found: {len(backup_files)}")
    for bf in backup_files[:10]:  # Show first 10
        print(f"  - {bf}")
    
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    if mail_count == 0:
        print("✅ mail_intake_pipeline_dossier is unreferenced (can be removed)")
    else:
        print(f"⚠️  mail_intake_pipeline_dossier has {mail_count} references")
    
    if backend_count == 0:
        print("✅ backend/ is unreferenced (can be removed)")
    else:
        print(f"⚠️  backend/ has {backend_count} references")
    
    if backup_files:
        print(f"⚠️  Found {len(backup_files)} backup files to review")
    
    print()
    print("Recommendations:")
    print("  - Remove mail_intake_pipeline_dossier/ if unreferenced")
    print("  - Remove backend/ if unreferenced")
    print("  - Review and remove .bak-* files")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
