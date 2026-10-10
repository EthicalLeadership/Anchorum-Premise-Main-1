"""End-to-end: two short runs (baseline, blackstar) plus a comparison.

Marked slow: takes ~10 seconds because it launches real workloads.
Run with `pytest -m "not slow"` for the fast suite; `pytest -m slow` for
these only.
"""
from __future__ import annotations
import json
import pathlib

import pytest

from harness import audit_run, compare_runs


REPO = pathlib.Path(__file__).resolve().parents[2]
WORKLOADS = REPO / "harness" / "workloads.yaml"

pytestmark = pytest.mark.slow


def _run(tmp_path: pathlib.Path, env: str) -> pathlib.Path:
    return audit_run.run(
        env=env,
        duration=4.0,
        sample_interval=1.0,
        workload_names=["cpu_burn"],
        outdir=tmp_path / "runs",
        workloads_path=WORKLOADS,
    )


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e_runs")
    baseline_dir = _run(tmp, "baseline")
    blackstar_dir = _run(tmp, "blackstar")
    return baseline_dir, blackstar_dir


def test_baseline_artifacts_exist(two_runs):
    baseline_dir, _ = two_runs
    assert (baseline_dir / "metrics.csv").is_file()
    assert (baseline_dir / "manifest.json").is_file()


def test_baseline_has_at_least_four_samples(two_runs):
    baseline_dir, _ = two_runs
    lines = (baseline_dir / "metrics.csv").read_text().splitlines()
    assert len(lines) >= 5


def test_manifest_shape(two_runs):
    baseline_dir, _ = two_runs
    m = json.loads((baseline_dir / "manifest.json").read_text())
    assert m["env"] == "baseline"
    assert m["orchestration_active"] is False
    assert m["blackstarctl_present"] is False
    assert m["samples_written"] >= 4
    assert len(m["workloads"]) == 1
    wl = m["workloads"][0]
    assert wl["name"] == "cpu_burn"
    assert wl["primary"] is True
    assert isinstance(wl["root_pid"], int)


def test_comparison_runs_against_real_data(two_runs, tmp_path):
    baseline_dir, blackstar_dir = two_runs
    outdir = tmp_path / "comparison"
    result = compare_runs.compare(baseline_dir, blackstar_dir, outdir)
    assert result["aligned_pairs"] >= 3
    for fname in ("comparison.json", "comparison.csv", "comparison.md"):
        assert (outdir / fname).is_file()


def test_main_cpu_sum_is_a_rate_not_cumulative(two_runs):
    """Regression: earlier code accumulated CPU-since-start and divided by
    a fixed interval, producing a monotonically-growing metric. It should
    now be a per-window rate and roughly bounded."""
    baseline_dir, _ = two_runs
    lines = (baseline_dir / "metrics.csv").read_text().splitlines()
    header = lines[0].split(",")
    idx = header.index("main_cpu_sum_pct")
    values = []
    for row in lines[1:]:
        parts = row.split(",")
        if len(parts) <= idx or parts[idx] == "":
            continue
        try:
            values.append(float(parts[idx]))
        except ValueError:
            continue
    assert values, "no main_cpu_sum_pct samples"
    # The first sample has no prior ticks and must be 0.
    assert values[0] == 0.0, f"first sample should be 0, got {values[0]}"
    # The metric is a per-window rate bounded by worker count * 100%.
    # For cpu_burn --workers 4 this cannot exceed 400% by much; 520 gives
    # slack for scheduling jitter. The old cumulative implementation
    # would exceed this within a few samples.
    assert max(values) < 520.0, f"main_cpu_sum_pct reached {max(values)}"
    # Under real load the steady-state rate must be substantial; if the
    # metric silently returned zeros, this would fail.
    steady = [v for v in values[1:]]
    assert steady and max(steady) > 200.0, (
        f"expected steady-state CPU rate above 200%, got {steady}"
    )
