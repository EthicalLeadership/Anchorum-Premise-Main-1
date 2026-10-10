"""Import smoke test: every source module under the tracked packages must
import cleanly. Catches missing dependencies (e.g. a pip package absent
from requirements.txt) at test-collection time rather than at runtime.

Modules are discovered dynamically; a new module is tested the moment it
lands. Intentional skips go in _KNOWN_OPTIONAL with a comment naming the
missing dependency.
"""
from __future__ import annotations
import importlib
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _discover(package_dir: pathlib.Path, prefix: str):
    if not package_dir.is_dir():
        return
    for entry in sorted(package_dir.rglob("*.py")):
        if "__pycache__" in entry.parts:
            continue
        parts = list(entry.relative_to(package_dir).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
            if not parts:
                continue
        yield ".".join([prefix] + parts)


_PACKAGES = [
    ("dossier_pipeline", _REPO_ROOT / "dossier_pipeline"),
    ("ccsp",             _REPO_ROOT / "ccsp"),
    ("factory",          _REPO_ROOT / "factory"),
    ("evals",            _REPO_ROOT / "evals"),
    ("dossier_enforcement", _REPO_ROOT / "dossier_enforcement"),
    ("ci",               _REPO_ROOT / "ci"),
]

_KNOWN_OPTIONAL: set[str] = set()

_ALL = sorted({
    m
    for prefix, path in _PACKAGES
    for m in _discover(path, prefix)
})


@pytest.mark.parametrize("module_name", _ALL, ids=_ALL)
def test_module_imports(module_name):
    if module_name in _KNOWN_OPTIONAL:
        pytest.skip(f"{module_name}: optional dep not in requirements")
    importlib.import_module(module_name)
