"""Audit harness runner.

Launches one or more workloads, samples metrics at a fixed interval for a
fixed duration, writes a metrics CSV and a manifest JSON. Stdlib only.

    python3 -m harness.audit_run --env baseline --duration 12 ...

Output layout:
    <outdir>/<ts>/<env>/metrics.csv
    <outdir>/<ts>/<env>/manifest.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

import yaml

from harness.laneop import classify_main_tasks
from harness.orchestration import disable_blackstar, enable_blackstar
from harness.src.metrics import cpu_ram, ctx_switch, disk_io, gpu, procbg


HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent


# Fixed column order. Any new metric is appended; existing columns never
# change name. Nulls are written as empty strings.
CSV_COLUMNS = [
    "ts_utc",
    "t_rel_s",
    # cpu_ram
    "cpu_util",
    "load1",
    "load5",
    "load15",
    "mem_total_kb",
    "mem_used_kb",
    "mem_available_kb",
    "main_pids_live",
    "main_cpu_sum_pct",
    "main_rss_sum_kb",
    # ctx_switch
    "ctxt_hz",
    "ctxt_total",
    # disk_io
    "disk_read_bps",
    "disk_write_bps",
    "disk_util",
    # gpu
    "gpu_present",
    "gpu_count",
    "gpu_util_max_pct",
    "gpu_mem_used_mb_sum",
    "gpu_mem_total_mb_sum",
    # procbg
    "procbg_count",
]


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _expand_command(cmd: list[str]) -> list[str]:
    """Substitute {python} and {here} placeholders."""
    out = []
    for tok in cmd:
        out.append(tok.replace("{python}", sys.executable)
                      .replace("{here}", str(HERE / "scripts")))
    return out


def _load_workloads(path: pathlib.Path) -> dict[str, dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "workloads" not in data:
        raise ValueError("workloads.yaml must contain a 'workloads' list")
    out: dict[str, dict] = {}
    for wl in data["workloads"]:
        if "name" not in wl or "command" not in wl:
            raise ValueError(f"workload entry missing name/command: {wl!r}")
        out[wl["name"]] = wl
    return out


def _start_workload(wl: dict) -> subprocess.Popen:
    argv = _expand_command(list(wl["command"]))
    return subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def _shutdown(procs: list[subprocess.Popen], *, sig=signal.SIGTERM) -> None:
    for p in procs:
        if p.poll() is None:
            try:
                os.killpg(p.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
    deadline = time.monotonic() + 3.0
    for p in procs:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            p.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def _row_from_samples(
    ts_utc: str,
    t_rel_s: float,
    cpu: dict, ctx: dict, disk: dict, gpu_d: dict, bg: dict,
) -> dict[str, Any]:
    return {
        "ts_utc": ts_utc,
        "t_rel_s": round(t_rel_s, 4),
        "cpu_util": cpu.get("cpu_util"),
        "load1": cpu.get("load1"),
        "load5": cpu.get("load5"),
        "load15": cpu.get("load15"),
        "mem_total_kb": cpu.get("mem_total_kb"),
        "mem_used_kb": cpu.get("mem_used_kb"),
        "mem_available_kb": cpu.get("mem_available_kb"),
        "main_pids_live": cpu.get("main_pids_live"),
        "main_cpu_sum_pct": cpu.get("main_cpu_sum_pct"),
        "main_rss_sum_kb": cpu.get("main_rss_sum_kb"),
        "ctxt_hz": ctx.get("ctxt_hz"),
        "ctxt_total": ctx.get("ctxt_total"),
        "disk_read_bps": disk.get("disk_read_bps"),
        "disk_write_bps": disk.get("disk_write_bps"),
        "disk_util": disk.get("disk_util"),
        "gpu_present": gpu_d.get("gpu_present"),
        "gpu_count": gpu_d.get("gpu_count"),
        "gpu_util_max_pct": gpu_d.get("gpu_util_max_pct"),
        "gpu_mem_used_mb_sum": gpu_d.get("gpu_mem_used_mb_sum"),
        "gpu_mem_total_mb_sum": gpu_d.get("gpu_mem_total_mb_sum"),
        "procbg_count": bg.get("procbg_count"),
    }


def _display_path(p: pathlib.Path) -> str:
    """Return a path relative to REPO_ROOT when possible, absolute otherwise.

    When the harness is invoked from the CLI with the default outdir, paths
    are under REPO_ROOT and the relative form is cleaner in the manifest.
    When outdir is somewhere else (e.g. pytest tmp_path), we fall back to
    the absolute path rather than raise.
    """
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def run(
    *,
    env: str,
    duration: float,
    sample_interval: float,
    workload_names: list[str],
    outdir: pathlib.Path,
    workloads_path: pathlib.Path,
) -> pathlib.Path:
    if env not in ("baseline", "blackstar"):
        raise ValueError(f"--env must be baseline|blackstar, got {env!r}")
    if duration <= 0 or sample_interval <= 0:
        raise ValueError("duration and sample-interval must be positive")

    # Resolve outdir immediately so downstream path operations are
    # consistent (relative_to() refuses to mix absolute and relative).
    outdir = pathlib.Path(outdir).resolve()
    workloads_path = pathlib.Path(workloads_path).resolve()

    catalog = _load_workloads(workloads_path)
    missing = [n for n in workload_names if n not in catalog]
    if missing:
        raise ValueError(f"unknown workloads: {missing}; known: {sorted(catalog)}")

    # Enable orchestration if blackstar.
    orch_active = False
    if env == "blackstar":
        orch_active = enable_blackstar(quiet=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = outdir / ts / env
    run_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = run_dir / "metrics.csv"
    manifest_path = run_dir / "manifest.json"

    procs: list[subprocess.Popen] = []
    pid_by_workload: dict[str, int] = {}

    try:
        # Longest warmup among selected workloads.
        warmup = max(catalog[n].get("warmup_s", 0) for n in workload_names)

        for n in workload_names:
            p = _start_workload(catalog[n])
            procs.append(p)
            pid_by_workload[n] = p.pid

        time.sleep(float(warmup))

        main_pids: set[int] = set()
        for n in workload_names:
            root = pid_by_workload[n]
            if catalog[n].get("primary", False):
                main_pids |= classify_main_tasks([root])

        sampling_start = time.monotonic()
        deadline = sampling_start + float(duration)
        samples_written = 0

        with metrics_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()

            next_tick = sampling_start
            while time.monotonic() < deadline:
                now = time.monotonic()
                if now < next_tick:
                    time.sleep(min(0.05, next_tick - now))
                    continue
                t_rel_s = now - sampling_start
                ts_utc = _iso_now()

                cpu = cpu_ram.collect(main_pids, sample_interval=sample_interval)
                ctx = ctx_switch.collect(sample_interval=sample_interval)
                disk = disk_io.collect(sample_interval=sample_interval)
                gpu_d = gpu.collect(main_pids, sample_interval=sample_interval)
                bg = procbg.collect(main_pids)

                writer.writerow(_row_from_samples(ts_utc, t_rel_s,
                                                  cpu, ctx, disk, gpu_d, bg))
                f.flush()
                samples_written += 1
                next_tick += sample_interval

        manifest = {
            "env": env,
            "orchestration_active": orch_active,
            "blackstarctl_present": __import__("harness.orchestration",
                                                fromlist=["is_available"]).is_available(),
            "started_utc": ts,
            "duration_s": float(duration),
            "sample_interval_s": float(sample_interval),
            "samples_written": samples_written,
            "workloads": [
                {
                    "name": n,
                    "command": _expand_command(list(catalog[n]["command"])),
                    "root_pid": pid_by_workload[n],
                    "primary": bool(catalog[n].get("primary", False)),
                }
                for n in workload_names
            ],
            "main_pids_snapshot": sorted(main_pids),
            "metrics_path": _display_path(metrics_path),
            "manifest_path": _display_path(manifest_path),
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )

    finally:
        _shutdown(procs)
        if env == "blackstar":
            disable_blackstar(quiet=True)

    return run_dir


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harness.audit_run")
    ap.add_argument("--env", choices=("baseline", "blackstar"), required=True)
    ap.add_argument("--duration", type=float, default=12.0)
    ap.add_argument("--sample-interval", type=float, default=1.0)
    ap.add_argument("--workloads", default="cpu_burn",
                    help="comma-separated workload names from workloads.yaml")
    ap.add_argument("--outdir", default="harness/runs")
    ap.add_argument("--workloads-file",
                    default=str(HERE / "workloads.yaml"))
    args = ap.parse_args(argv)

    names = [n.strip() for n in args.workloads.split(",") if n.strip()]
    if not names:
        print("--workloads must name at least one workload", file=sys.stderr)
        return 2

    try:
        run_dir = run(
            env=args.env,
            duration=args.duration,
            sample_interval=args.sample_interval,
            workload_names=names,
            outdir=pathlib.Path(args.outdir),
            workloads_path=pathlib.Path(args.workloads_file),
        )
    except Exception as e:
        print(f"audit_run: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"audit_run: wrote {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
