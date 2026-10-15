"""
Healing Engine Constrained Autofix System
=============================================
Each FailureCategory maps to a finite, ordered list of RepairActions.
No free-form code generation. Every action is drawn from the closed repair set.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Optional

from ci.classifier import FailureCategory, FailureRecord

# ---------------------------------------------------------------------------
# Repair action taxonomy
# ---------------------------------------------------------------------------

class RepairAction(Enum):
    # Dependency
    INSTALL_MISSING_PACKAGE     = auto()
    PIN_VERSION                 = auto()
    RESOLVE_LOCKFILE_MISMATCH   = auto()
    # Import
    ADD_MISSING_IMPORT          = auto()
    CORRECT_MODULE_PATH         = auto()
    # Config
    RESTORE_DEFAULT_CONFIG      = auto()
    REGENERATE_MISSING_KEYS     = auto()
    NORMALIZE_ENV_VARS          = auto()
    # Test
    RERUN_FLAKY_TEST            = auto()
    ISOLATE_UNSTABLE_TEST       = auto()
    # Build
    CLEAR_CACHE                 = auto()
    REBUILD_ENVIRONMENT         = auto()
    RESET_DEPENDENCY_GRAPH      = auto()
    # Sentinel
    NO_ACTION_AVAILABLE         = auto()


class RepairOutcome(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"


@dataclass
class RepairAttempt:
    failure_signature: str
    action: RepairAction
    outcome: RepairOutcome
    detail: str = ""
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Failure memory  (in-process; persisted to JSON for cross-run memory)
# ---------------------------------------------------------------------------

class FailureMemory:
    """
    Tracks every (signature, action) pair that has been attempted.
    Rule: never repeat a failed fix.
    Rule: escalate if same signature seen >= 3 times.
    """
    MAX_ATTEMPTS = 3

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self._log: dict[str, list[RepairAttempt]] = {}
        self._path = log_path

    def record(self, attempt: RepairAttempt) -> None:
        sig = attempt.failure_signature
        self._log.setdefault(sig, []).append(attempt)
        if self._path:
            self._persist()

    def attempts_for(self, signature: str) -> list[RepairAttempt]:
        return self._log.get(signature, [])

    def already_tried(self, signature: str, action: RepairAction) -> bool:
        return any(a.action == action for a in self.attempts_for(signature))

    def consecutive_failures(self, signature: str) -> int:
        return sum(
            1 for a in self.attempts_for(signature)
            if a.outcome == RepairOutcome.FAILURE
        )

    def exhausted(self, signature: str) -> bool:
        return self.consecutive_failures(signature) >= self.MAX_ATTEMPTS

    def _persist(self) -> None:
        assert self._path is not None
        data = {
            sig: [
                {
                    "action": a.action.name,
                    "outcome": a.outcome.value,
                    "detail": a.detail,
                    "timestamp": a.timestamp,
                }
                for a in attempts
            ]
            for sig, attempts in self._log.items()
        }
        self._path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Repair strategy table
# ---------------------------------------------------------------------------

# Maps each category to an ordered list of actions to try in sequence.
REPAIR_STRATEGIES: dict[FailureCategory, list[RepairAction]] = {
    FailureCategory.MISSING_DEPENDENCY:      [RepairAction.INSTALL_MISSING_PACKAGE,
                                              RepairAction.REBUILD_ENVIRONMENT],
    FailureCategory.VERSION_CONFLICT:        [RepairAction.PIN_VERSION,
                                              RepairAction.RESOLVE_LOCKFILE_MISMATCH,
                                              RepairAction.REBUILD_ENVIRONMENT],
    FailureCategory.IMPORT_FAILURE:          [RepairAction.INSTALL_MISSING_PACKAGE,
                                              RepairAction.ADD_MISSING_IMPORT,
                                              RepairAction.CORRECT_MODULE_PATH],
    FailureCategory.MISSING_TEST_DEPENDENCY: [RepairAction.INSTALL_MISSING_PACKAGE,
                                              RepairAction.REBUILD_ENVIRONMENT],
    FailureCategory.FLAKY_TEST:              [RepairAction.RERUN_FLAKY_TEST,
                                              RepairAction.ISOLATE_UNSTABLE_TEST],
    FailureCategory.ASSERTION_MISMATCH:      [],   # not auto-healable
    FailureCategory.CONFIG_ERROR:            [RepairAction.REGENERATE_MISSING_KEYS,
                                              RepairAction.RESTORE_DEFAULT_CONFIG,
                                              RepairAction.NORMALIZE_ENV_VARS],
    FailureCategory.INITIALIZATION_FAILURE:  [RepairAction.REGENERATE_MISSING_KEYS,
                                              RepairAction.CLEAR_CACHE,
                                              RepairAction.REBUILD_ENVIRONMENT],
    FailureCategory.VULNERABLE_DEPENDENCY:   [RepairAction.PIN_VERSION,
                                              RepairAction.INSTALL_MISSING_PACKAGE],
    FailureCategory.UNSAFE_CONFIG:           [RepairAction.NORMALIZE_ENV_VARS,
                                              RepairAction.RESTORE_DEFAULT_CONFIG],
    # Structural no strategy
    FailureCategory.COMPILATION_ERROR:       [],
    FailureCategory.UNDEFINED_REFERENCE:     [],
    FailureCategory.TYPE_MISMATCH:           [],
    FailureCategory.CRASH_ON_STARTUP:        [],
    FailureCategory.EXPOSED_SECRET:          [],
    FailureCategory.UNCLASSIFIED:            [],
}


# ---------------------------------------------------------------------------
# Action executors
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: Optional[str] = None) -> tuple[int, str]:
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=cwd, timeout=120
    )
    return result.returncode, result.stdout + result.stderr


def _extract_module_name(detail: str) -> Optional[str]:
    import re
    m = re.search(r"no module named '?([a-z0-9_\-]+)'?", detail, re.I)
    return m.group(1).replace("-", "_") if m else None


class RepairExecutor:
    """
    Executes a single RepairAction in the context of the current project.
    Returns (success: bool, detail: str).
    """

    def __init__(self, project_root: Path) -> None:
        self.root = project_root

    def execute(self, action: RepairAction, failure: FailureRecord) -> tuple[bool, str]:
        handler: dict[RepairAction, Callable[[], tuple[bool, str]]] = {
            RepairAction.INSTALL_MISSING_PACKAGE:   lambda: self._install_missing(failure),
            RepairAction.PIN_VERSION:               lambda: self._pin_version(failure),
            RepairAction.RESOLVE_LOCKFILE_MISMATCH: lambda: self._resolve_lockfile(),
            RepairAction.ADD_MISSING_IMPORT:        lambda: (False, "add-import requires human review"),
            RepairAction.CORRECT_MODULE_PATH:       lambda: (False, "module-path correction requires human review"),
            RepairAction.RESTORE_DEFAULT_CONFIG:    lambda: self._restore_config(),
            RepairAction.REGENERATE_MISSING_KEYS:   lambda: self._regen_keys(failure),
            RepairAction.NORMALIZE_ENV_VARS:        lambda: self._normalize_env(),
            RepairAction.RERUN_FLAKY_TEST:          lambda: (True, "flaky-rerun delegated to pipeline"),
            RepairAction.ISOLATE_UNSTABLE_TEST:     lambda: (False, "test isolation requires human review"),
            RepairAction.CLEAR_CACHE:               lambda: self._clear_cache(),
            RepairAction.REBUILD_ENVIRONMENT:       lambda: self._rebuild_env(),
            RepairAction.RESET_DEPENDENCY_GRAPH:    lambda: self._reset_dep_graph(),
            RepairAction.NO_ACTION_AVAILABLE:       lambda: (False, "no action available"),
        }
        fn = handler.get(action)
        if fn is None:
            return False, f"unknown action: {action}"
        return fn()

    # -- concrete actions ---------------------------------------------------

    def _install_missing(self, failure: FailureRecord) -> tuple[bool, str]:
        module = _extract_module_name(failure.detail) or _extract_module_name(failure.raw_output)
        if not module:
            return False, "could not extract module name from failure output"
        # Only install stdlib-safe known packages; never exec arbitrary strings
        allowed_prefixes = ("pytest", "setuptools", "pip", "wheel",
                            "cryptography", "email", "imaplib")
        if not any(module.startswith(p) for p in allowed_prefixes):
            return False, f"package '{module}' not in allowlist escalate to human"
        rc, out = _run([sys.executable, "-m", "pip", "install", "--quiet", module],
                       cwd=str(self.root))
        return rc == 0, out[:300]

    def _pin_version(self, failure: FailureRecord) -> tuple[bool, str]:
        rc, out = _run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--upgrade", "pip", "setuptools"],
            cwd=str(self.root)
        )
        return rc == 0, out[:300]

    def _resolve_lockfile(self) -> tuple[bool, str]:
        req = self.root / "requirements.txt"
        if not req.exists():
            return False, "requirements.txt not found"
        rc, out = _run(
            [sys.executable, "-m", "pip", "install", "--quiet", "-r", str(req)],
            cwd=str(self.root)
        )
        return rc == 0, out[:300]

    def _restore_config(self) -> tuple[bool, str]:
        example = self.root / "config_live.example.json"
        target = self.root / "config_live.json"
        if not example.exists():
            return False, "config_live.example.json not found"
        if target.exists():
            return True, "config_live.json already exists no restore needed"
        import shutil
        shutil.copy(example, target)
        return True, f"restored config_live.json from {example.name}"

    def _regen_keys(self, failure: FailureRecord) -> tuple[bool, str]:
        # Only regen if there is a template to derive from
        example = self.root / "config_live.example.json"
        target = self.root / "config_live.json"
        if not example.exists():
            return False, "no config template to regenerate from"
        if not target.exists():
            return self._restore_config()
        try:
            import json as _json
            template = _json.loads(example.read_text())
            current = _json.loads(target.read_text())
            added = []
            for key, val in template.items():
                if key not in current:
                    current[key] = val
                    added.append(key)
            if added:
                target.write_text(_json.dumps(current, indent=2))
                return True, f"regenerated missing keys: {added}"
            return True, "no missing keys found"
        except Exception as exc:
            return False, str(exc)

    def _normalize_env(self) -> tuple[bool, str]:
        # Strip any env vars that look like leaked secrets from .env if present
        dotenv = self.root / ".env"
        if not dotenv.exists():
            return True, ".env not present nothing to normalize"
        lines = dotenv.read_text().splitlines()
        safe = [l for l in lines if not any(
            kw in l.upper() for kw in ("PASSWORD", "SECRET", "TOKEN", "API_KEY")
        )]
        if len(safe) < len(lines):
            dotenv.write_text("\n".join(safe) + "\n")
            return True, f"removed {len(lines) - len(safe)} sensitive env lines"
        return True, "no normalization needed"

    def _clear_cache(self) -> tuple[bool, str]:
        import shutil
        cleared = []
        for d in [self.root / "__pycache__",
                  self.root / "dossier_pipeline" / "__pycache__",
                  self.root / ".pytest_cache"]:
            if d.exists():
                shutil.rmtree(d)
                cleared.append(str(d))
        rc, out = _run([sys.executable, "-m", "pip", "cache", "purge"],
                       cwd=str(self.root))
        return True, f"cleared: {cleared}; pip cache: {out[:100]}"

    def _rebuild_env(self) -> tuple[bool, str]:
        req = self.root / "requirements.txt"
        if not req.exists():
            return True, "no requirements.txt nothing to rebuild"
        rc, out = _run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--force-reinstall", "-r", str(req)],
            cwd=str(self.root)
        )
        return rc == 0, out[:300]

    def _reset_dep_graph(self) -> tuple[bool, str]:
        ok1, d1 = self._clear_cache()
        ok2, d2 = self._rebuild_env()
        return ok1 and ok2, f"{d1} | {d2}"
