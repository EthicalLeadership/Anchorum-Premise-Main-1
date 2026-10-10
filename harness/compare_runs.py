"""Compare two harness runs (baseline vs blackstar).

Reads metrics.csv from each run directory, aligns on t_rel_s by
nearest-neighbour within a tolerance, computes per-metric median and P95
for both runs, and writes:

    comparison.json   structured data
    comparison.md     human-readable summary
    comparison.csv    per-metric table

    python3 -m harness.compare_runs \
        --baseline harness/runs/<ts>/baseline \
        --blackstar harness/runs/<ts>/blackstar \
        --outdir harness/runs/<ts>/comparison
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import statistics
import sys
from typing import Any


# Metrics we care about; each has a "direction of goodness" for the summary.
#   lower_better  — decrease is an improvement
#   higher_better — increase is an improvement
#   neutral       — direction not judged, delta reported as-is
METRIC_DIRECTIONS: dict[str, str] = {
    "cpu_util": "neutral",
    "main_cpu_sum_pct": "neutral",
    "main_rss_sum_kb": "lower_better",
    "ctxt_hz": "lower_better",
    "disk_read_bps": "neutral",
    "disk_write_bps": "neutral",
    "disk_util": "lower_better",
    "gpu_util_max_pct": "neutral",
    "gpu_mem_used_mb_sum": "lower_better",
    "procbg_count": "lower_better",
}


def _read_csv(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"missing metrics.csv: {path}")
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed: dict[str, Any] = {}
            for k, v in row.items():
                if v in (None, ""):
                    parsed[k] = None
                    continue
                try:
                    parsed[k] = float(v)
                except ValueError:
                    parsed[k] = v
            rows.append(parsed)
    return rows


def _numeric_columns(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    cols = []
    for k in rows[0]:
        if k in ("ts_utc", "t_rel_s"):
            continue
        # Include column if any row has a numeric value.
        if any(isinstance(r.get(k), float) for r in rows):
            cols.append(k)
    return cols


def _align(
    baseline: list[dict[str, Any]],
    blackstar: list[dict[str, Any]],
    tolerance: float,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Align by t_rel_s using nearest-neighbour within tolerance.

    Both lists are assumed to be sorted by t_rel_s. Walking two pointers
    keeps this O(n+m).
    """
    b = sorted(baseline, key=lambda r: r.get("t_rel_s", 0.0))
    x = sorted(blackstar, key=lambda r: r.get("t_rel_s", 0.0))
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    i = j = 0
    while i < len(b) and j < len(x):
        bt = b[i].get("t_rel_s", 0.0)
        xt = x[j].get("t_rel_s", 0.0)
        diff = abs(bt - xt)
        if diff <= tolerance:
            pairs.append((b[i], x[j]))
            i += 1
            j += 1
        elif bt < xt:
            i += 1
        else:
            j += 1
    return pairs


def _percentile(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    # Linear interpolation between nearest ranks.
    k = (len(sorted_vals) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _median_and_p95(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "p95": None, "n": 0}
    sv = sorted(values)
    return {
        "median": statistics.median(sv),
        "p95": _percentile(sv, 0.95),
        "n": len(sv),
    }


def _pct_delta(b: float | None, x: float | None) -> float | None:
    if b is None or x is None or b == 0:
        return None
    return (x - b) / abs(b) * 100.0


def compare(baseline_dir: pathlib.Path,
            blackstar_dir: pathlib.Path,
            outdir: pathlib.Path,
            *, tolerance: float = 0.5) -> dict[str, Any]:
    b_rows = _read_csv(baseline_dir / "metrics.csv")
    x_rows = _read_csv(blackstar_dir / "metrics.csv")
    cols = sorted(set(_numeric_columns(b_rows)) | set(_numeric_columns(x_rows)))

    pairs = _align(b_rows, x_rows, tolerance=tolerance)

    per_metric: dict[str, dict[str, Any]] = {}
    for col in cols:
        b_vals: list[float] = []
        x_vals: list[float] = []
        for b_row, x_row in pairs:
            bv = b_row.get(col)
            xv = x_row.get(col)
            if isinstance(bv, float):
                b_vals.append(bv)
            if isinstance(xv, float):
                x_vals.append(xv)
        b_stats = _median_and_p95(b_vals)
        x_stats = _median_and_p95(x_vals)
        per_metric[col] = {
            "direction": METRIC_DIRECTIONS.get(col, "neutral"),
            "baseline": b_stats,
            "blackstar": x_stats,
            "median_delta": (
                None if b_stats["median"] is None or x_stats["median"] is None
                else x_stats["median"] - b_stats["median"]
            ),
            "median_pct": _pct_delta(b_stats["median"], x_stats["median"]),
            "p95_delta": (
                None if b_stats["p95"] is None or x_stats["p95"] is None
                else x_stats["p95"] - b_stats["p95"]
            ),
            "p95_pct": _pct_delta(b_stats["p95"], x_stats["p95"]),
        }

    result = {
        "baseline_dir": str(baseline_dir),
        "blackstar_dir": str(blackstar_dir),
        "aligned_pairs": len(pairs),
        "tolerance_s": tolerance,
        "metrics": per_metric,
    }

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "comparison.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )

    # CSV
    with (outdir / "comparison.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "metric", "direction",
            "baseline_median", "blackstar_median", "median_delta", "median_pct",
            "baseline_p95", "blackstar_p95", "p95_delta", "p95_pct",
        ])
        for col in sorted(per_metric):
            m = per_metric[col]
            w.writerow([
                col, m["direction"],
                m["baseline"]["median"], m["blackstar"]["median"],
                m["median_delta"], m["median_pct"],
                m["baseline"]["p95"], m["blackstar"]["p95"],
                m["p95_delta"], m["p95_pct"],
            ])

    # Markdown
    md = []
    md.append("# BlackStar vs Baseline comparison")
    md.append("")
    md.append(f"- baseline:  `{baseline_dir}`")
    md.append(f"- blackstar: `{blackstar_dir}`")
    md.append(f"- aligned sample pairs: {len(pairs)}")
    md.append("")
    md.append("| metric | direction | baseline median | blackstar median | Δ median | Δ median % | baseline P95 | blackstar P95 | Δ P95 % |")
    md.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for col in sorted(per_metric):
        m = per_metric[col]
        def _f(v):
            return "—" if v is None else f"{v:,.3f}"
        def _p(v):
            return "—" if v is None else f"{v:+.2f}%"
        md.append(
            f"| `{col}` | {m['direction']} | {_f(m['baseline']['median'])} | "
            f"{_f(m['blackstar']['median'])} | "
            f"{_f(m['median_delta'])} | {_p(m['median_pct'])} | "
            f"{_f(m['baseline']['p95'])} | {_f(m['blackstar']['p95'])} | "
            f"{_p(m['p95_pct'])} |"
        )
    (outdir / "comparison.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harness.compare_runs")
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--blackstar", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--tolerance", type=float, default=0.5)
    args = ap.parse_args(argv)

    try:
        result = compare(
            pathlib.Path(args.baseline),
            pathlib.Path(args.blackstar),
            pathlib.Path(args.outdir),
            tolerance=args.tolerance,
        )
    except Exception as e:
        print(f"compare_runs: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    n = result["aligned_pairs"]
    print(f"compare_runs: {n} aligned pairs, wrote {args.outdir}")
    return 0 if n > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
