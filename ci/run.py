"""
CI Entry Point + Report Renderer
==================================
Usage:
    python -m ci.run [--project-root PATH] [--memory-log PATH]

Exits 0 on DEPLOYABLE, non-zero on NON-DEPLOYABLE.
"""
from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

from ci.healer import RepairOutcome
from ci.runner import PipelineReport, StageStatus, SystemState, run_pipeline

# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

_SEP = "─" * 70
_SEP_THIN = "·" * 70

_STATE_SYMBOL = {
    SystemState.HEALTHY:  "✅ HEALTHY",
    SystemState.DEGRADED: "⚠  DEGRADED (healed)",
    SystemState.UNSTABLE: "⚠  UNSTABLE (multiple heals)",
    SystemState.BROKEN:   "❌ BROKEN",
}

_STATUS_SYMBOL = {
    StageStatus.PASS:    "✅ PASS",
    StageStatus.FAIL:    "❌ FAIL",
    StageStatus.HEALED:  "🔧 HEALED",
    StageStatus.SKIPPED: "⏭  SKIPPED",
}


def render(report: PipelineReport) -> str:
    lines: list[str] = []
    a = lines.append

    a("")
    a(_SEP)
    a("  DOSSIER-PIPELINE SELF-HEALING CI PIPELINE REPORT")
    a(_SEP)

    # Stage summary table
    a("")
    a("  PIPELINE STAGES")
    a(_SEP_THIN)
    for sr in report.stages:
        sym = _STATUS_SYMBOL.get(sr.status, sr.status.value)
        a(f"  {sr.name.upper():<12} {sym:<22}  {sr.duration_s:.2f}s")
    a(_SEP_THIN)

    # Failures + heal detail
    failed_stages = [sr for sr in report.stages if sr.failure]
    if failed_stages:
        a("")
        a("  FAILURE + HEALING DETAIL")
        for sr in failed_stages:
            assert sr.failure is not None
            a("")
            a(f"  Stage    : {sr.name}")
            a(f"  Category : {sr.failure.category.name}")
            a(f"  Severity : {sr.failure.severity.value}")
            a(f"  Detail   : {sr.failure.detail[:120]}")
            if sr.heal_attempts:
                a("  Repairs  :")
                for att in sr.heal_attempts:
                    sym = "✅" if att.outcome == RepairOutcome.SUCCESS else "❌"
                    a(f"    {sym} {att.action.name:<38} {att.detail[:60]}")
            else:
                a("  Repairs  : none attempted")
        a("")
        a(_SEP_THIN)

    # Healing summary
    a("")
    a("  HEALING SUMMARY")
    a(_SEP_THIN)
    repairs_tried = sum(len(sr.heal_attempts) for sr in report.stages)
    repairs_ok = sum(
        sum(1 for a_ in sr.heal_attempts if a_.outcome == RepairOutcome.SUCCESS)
        for sr in report.stages
    )
    a(f"  Heal cycles    : {report.heal_cycles}")
    a(f"  Repairs tried  : {repairs_tried}")
    a(f"  Repairs OK     : {repairs_ok}")
    a(f"  Repairs failed : {repairs_tried - repairs_ok}")

    # System state
    a("")
    a("  SYSTEM STATE")
    a(_SEP_THIN)
    a(f"  {_STATE_SYMBOL.get(report.system_state, report.system_state.value)}")
    a(f"  Duration       : {report.duration_s:.2f}s")

    # Final verdict
    a("")
    a(_SEP)
    if report.deployable:
        a("  FINAL VERDICT: ✅ DEPLOYABLE (HEALED)" if report.heal_cycles > 0
          else "  FINAL VERDICT: ✅ DEPLOYABLE")
    else:
        a("  FINAL VERDICT: ❌ NON-DEPLOYABLE human intervention required")
    a(_SEP)
    a("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Self-healing CI pipeline for DOSSIER-PIPELINE"
    )
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).parent.parent),
        help="Path to project root (default: parent of ci/)",
    )
    parser.add_argument(
        "--memory-log",
        default=None,
        help="Path to persist failure memory JSON (optional)",
    )
    args = parser.parse_args(argv)

    memory_path = Path(args.memory_log) if args.memory_log else None

    print(f"\n[CI] Executing pipeline root: {args.project_root}")
    print("[CI] Entering pipeline execution...\n")

    report = run_pipeline(
        project_root=args.project_root,
        memory_path=memory_path,
    )

    print(render(report))

    return 0 if report.deployable else 1


if __name__ == "__main__":
    sys.exit(main())
