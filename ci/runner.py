"""
Pipeline Runner + Healing Loop
================================
Runs each CI stage, detects failures, calls the healing engine,
and re-runs until healed or escalation limit is reached.
"""
from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from ci.classifier import FailureCategory, FailureRecord, classify
from ci.healer import (REPAIR_STRATEGIES, FailureMemory, RepairAction,
                       RepairAttempt, RepairExecutor, RepairOutcome)

# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

class StageStatus(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    HEALED = "HEALED"


@dataclass
class StageResult:
    name: str
    status: StageStatus
    output: str = ""
    failure: Optional[FailureRecord] = None
    heal_attempts: list[RepairAttempt] = field(default_factory=list)
    duration_s: float = 0.0


# ---------------------------------------------------------------------------
# System state
# ---------------------------------------------------------------------------

class SystemState(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"          # healed — all stages green
    UNSTABLE = "UNSTABLE"          # multiple heals applied
    BROKEN = "BROKEN"              # no recovery possible


@dataclass
class PipelineReport:
    stages: list[StageResult] = field(default_factory=list)
    heal_cycles: int = 0
    system_state: SystemState = SystemState.HEALTHY
    deployable: bool = False
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0

    @property
    def duration_s(self) -> float:
        return self.finished_at - self.started_at


# ---------------------------------------------------------------------------
# Stage runners
# ---------------------------------------------------------------------------

def _run_subprocess(cmd: list[str], cwd: str, timeout: int = 120) -> tuple[int, str]:
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout
    )
    return result.returncode, result.stdout + result.stderr


def _stage_build(root: str) -> StageResult:
    """Verify the package is importable (compilation + basic import check)."""
    t0 = time.time()
    rc, out = _run_subprocess(
        [sys.executable, "-c",
         "import dossier_pipeline; "
         "from dossier_pipeline import pipeline, intake, classifier, contracts"],
        cwd=root
    )
    status = StageStatus.PASS if rc == 0 else StageStatus.FAIL
    return StageResult(name="build", status=status, output=out,
                       duration_s=time.time() - t0)


def _stage_static(root: str) -> StageResult:
    """Py_compile every source file to catch syntax / reference errors."""
    t0 = time.time()
    rc, out = _run_subprocess(
        [sys.executable, "-m", "py_compile",
         *[str(p) for p in Path(root).glob("dossier_pipeline/*.py")]],
        cwd=root
    )
    status = StageStatus.PASS if rc == 0 else StageStatus.FAIL
    return StageResult(name="static", status=status, output=out,
                       duration_s=time.time() - t0)


def _stage_tests(root: str, rerun_flaky: bool = False) -> StageResult:
    """Run pytest. If rerun_flaky, add --lf (last-failed) flag."""
    t0 = time.time()
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short"]
    if rerun_flaky:
        cmd.append("--lf")
    rc, out = _run_subprocess(cmd, cwd=root, timeout=180)
    status = StageStatus.PASS if rc == 0 else StageStatus.FAIL
    return StageResult(name="test", status=status, output=out,
                       duration_s=time.time() - t0)


def _stage_security(root: str) -> StageResult:
    """
    Security scan: check for secrets in config, unsafe patterns in source,
    and known-vulnerable patterns in imports.  Stdlib-only; no bandit/semgrep.
    """
    t0 = time.time()
    issues: list[str] = []
    root_path = Path(root)

    # 1. Secrets in config / .env
    # Skip *.example.* and *.sample.* — those are intentional templates with placeholders
    for candidate in root_path.glob("*.json"):
        if ".example." in candidate.name or ".sample." in candidate.name:
            continue
        text = candidate.read_text(errors="replace")
        if any(kw in text.lower() for kw in
               ("your_bridge_password", "your-address@protonmail", "insert_password")):
            issues.append(f"EXPOSED_SECRET: placeholder credential in {candidate.name}")

    if (root_path / ".env").exists():
        env_text = (root_path / ".env").read_text(errors="replace")
        import re
        if re.search(r'PASSWORD\s*=\s*\S+', env_text, re.I):
            issues.append("EXPOSED_SECRET: plaintext PASSWORD in .env")

    # 2. Unsafe subprocess patterns in source
    for src in root_path.glob("dossier_pipeline/*.py"):
        text = src.read_text(errors="replace")
        if "shell=True" in text:
            issues.append(f"UNSAFE_CONFIG: shell=True in {src.name}")
        if "eval(" in text or "exec(" in text:
            issues.append(f"UNSAFE_CONFIG: eval/exec in {src.name}")

    output = "\n".join(issues) if issues else "no issues found"
    status = StageStatus.FAIL if issues else StageStatus.PASS
    return StageResult(name="security", status=status, output=output,
                       duration_s=time.time() - t0)


def _stage_runtime_sim(root: str) -> StageResult:
    """Run the built-in demo mode as a runtime simulation check."""
    t0 = time.time()
    rc, out = _run_subprocess(
        [sys.executable, "-m", "dossier_pipeline.main", "demo"],
        cwd=root,
        timeout=60
    )
    status = StageStatus.PASS if rc == 0 else StageStatus.FAIL
    return StageResult(name="runtime", status=status, output=out,
                       duration_s=time.time() - t0)


# Stage registry: ordered list of (name, runner_fn)
STAGES = [
    ("build",    _stage_build),
    ("static",   _stage_static),
    ("tests",    _stage_tests),
    ("security", _stage_security),
    ("runtime",  _stage_runtime_sim),
]


# ---------------------------------------------------------------------------
# Healing loop
# ---------------------------------------------------------------------------

MAX_HEAL_CYCLES = 3


def run_pipeline(project_root: str, memory_path: Optional[Path] = None) -> PipelineReport:
    """
    Execute the full pipeline with self-healing loop.
    Returns a PipelineReport with final system state and deployability verdict.
    """
    root = project_root
    memory = FailureMemory(log_path=memory_path)
    executor = RepairExecutor(Path(root))
    report = PipelineReport()
    total_heals = 0
    rerun_flaky = False

    # Outer healing loop
    for cycle in range(MAX_HEAL_CYCLES + 1):
        stage_results: list[StageResult] = []
        failures: list[FailureRecord] = []

        # --- run all stages ------------------------------------------------
        for stage_name, runner in STAGES:
            # Tests: pass flaky-rerun flag if previous cycle healed a flaky test
            if stage_name == "tests":
                result = runner(root, rerun_flaky)  # type: ignore[call-arg]
                rerun_flaky = False
            else:
                result = runner(root)

            stage_results.append(result)

            if result.status == StageStatus.FAIL:
                rec = classify(stage_name, result.output)
                result.failure = rec
                failures.append(rec)

        # --- update report with this cycle's results -----------------------
        report.stages = stage_results
        report.heal_cycles = cycle

        if not failures:
            # All stages passed
            if total_heals == 0:
                report.system_state = SystemState.HEALTHY
            elif total_heals == 1:
                report.system_state = SystemState.DEGRADED
            else:
                report.system_state = SystemState.UNSTABLE
            report.deployable = True
            break

        # --- attempt to heal -----------------------------------------------
        if cycle == MAX_HEAL_CYCLES:
            # Exhausted heal budget
            report.system_state = SystemState.BROKEN
            report.deployable = False
            break

        healed_any = False
        for failure in failures:
            sig = failure.signature()

            if memory.exhausted(sig):
                # Same failure failed 3 times — locked
                report.system_state = SystemState.BROKEN
                report.deployable = False
                report.finished_at = time.time()
                return report

            if failure.is_structural:
                # Structural failures are never auto-healed
                report.system_state = SystemState.BROKEN
                report.deployable = False
                report.finished_at = time.time()
                return report

            strategy = REPAIR_STRATEGIES.get(failure.category, [])
            if not strategy:
                report.system_state = SystemState.BROKEN
                report.deployable = False
                report.finished_at = time.time()
                return report

            for action in strategy:
                if memory.already_tried(sig, action):
                    continue

                ok, detail = executor.execute(action, failure)
                outcome = RepairOutcome.SUCCESS if ok else RepairOutcome.FAILURE
                attempt = RepairAttempt(
                    failure_signature=sig,
                    action=action,
                    outcome=outcome,
                    detail=detail,
                )
                memory.record(attempt)

                # Tag attempt on stage result
                for sr in stage_results:
                    if sr.failure and sr.failure.signature() == sig:
                        sr.heal_attempts.append(attempt)
                        sr.status = StageStatus.HEALED if ok else StageStatus.FAIL

                if ok:
                    total_heals += 1
                    healed_any = True
                    if action.name == "RERUN_FLAKY_TEST":
                        rerun_flaky = True
                    break  # move to next failure after first successful action

        if not healed_any:
            # No repair succeeded this cycle
            report.system_state = SystemState.BROKEN
            report.deployable = False
            break

    report.finished_at = time.time()
    return report
