"""CPU util, loadavg, per-main-PID CPU and RSS, system RAM totals."""
from __future__ import annotations

import pathlib
from typing import Iterable

from ._proc import (PROC, page_size, pid_stat, proc_stat_totals, read_text,
                    user_hz)


_LAST: dict | None = None

# Per-pid cache: {pid: (utime, stime, monotonic_t_at_last_read)}.
# Used to compute per-window CPU rate for main tasks, rather than
# cumulative-since-process-start. Reset explicitly via reset_state().
_PER_PID: dict[int, tuple[int, int, float]] = {}


def reset_state() -> None:
    """Clear all accumulator state. Call between independent runs so a
    fresh harness instance does not inherit stale deltas from a previous
    sampling session."""
    global _LAST
    _LAST = None
    _PER_PID.clear()


def _cpu_util_from_totals(now: dict, prev: dict | None) -> float | None:
    """Compute aggregate CPU utilization (0.0-1.0) from two /proc/stat
    cpu-total snapshots. Returns None if prev is None (first sample)."""
    if prev is None:
        return None
    busy_now = now["user"] + now["nice"] + now["system"] + now["irq"] + now["softirq"] + now["steal"]
    busy_prev = prev["user"] + prev["nice"] + prev["system"] + prev["irq"] + prev["softirq"] + prev["steal"]
    total_now = busy_now + now["idle"] + now["iowait"]
    total_prev = busy_prev + prev["idle"] + prev["iowait"]
    d_total = total_now - total_prev
    d_busy = busy_now - busy_prev
    if d_total <= 0:
        return None
    return d_busy / d_total


def _meminfo() -> dict | None:
    raw = read_text(PROC / "meminfo")
    if raw is None:
        return None
    out: dict[str, int] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        parts = val.strip().split()
        if not parts:
            continue
        try:
            out[key] = int(parts[0])  # kB
        except ValueError:
            continue
    return out


def collect(main_pids: Iterable[int], *, sample_interval: float) -> dict:
    """Return a metrics dict. All fields are always present; individual
    values may be None if their source was unavailable at sample time.

    sample_interval is informational for the per-pid CPU-rate calculation:
    the rate uses the actual monotonic-clock delta between calls, not this
    value, so the caller may sample at any cadence. The parameter is
    retained because the CLI passes it and because callers may rely on it
    being present in the signature."""
    global _LAST
    totals = proc_stat_totals()
    util = _cpu_util_from_totals(totals, _LAST) if totals else None
    _LAST = totals

    load = read_text(PROC / "loadavg")
    load1 = load5 = load15 = None
    if load:
        parts = load.split()
        if len(parts) >= 3:
            try:
                load1, load5, load15 = float(parts[0]), float(parts[1]), float(parts[2])
            except ValueError:
                pass

    mem = _meminfo()
    mem_total_kb = mem.get("MemTotal") if mem else None
    mem_avail_kb = mem.get("MemAvailable") if mem else None
    mem_used_kb = None
    if mem_total_kb is not None and mem_avail_kb is not None:
        mem_used_kb = mem_total_kb - mem_avail_kb

    import time as _time
    now_mono = _time.monotonic()
    hz = user_hz()
    pg = page_size()
    cpu_rate_sum = 0.0   # sum of per-pid CPU-rate fractions (1.0 = 1 core busy)
    rss_sum_kb = 0.0
    n_live = 0
    seen_pids: set[int] = set()
    for pid in main_pids:
        st = pid_stat(pid)
        if st is None:
            continue
        seen_pids.add(pid)
        n_live += 1
        total_ticks = st["utime"] + st["stime"]
        prev = _PER_PID.get(pid)
        if prev is not None:
            prev_ticks, prev_t = prev
            dt = now_mono - prev_t
            if dt > 0:
                d_ticks = total_ticks - prev_ticks
                if d_ticks >= 0:
                    cpu_rate_sum += (d_ticks / hz) / dt
        _PER_PID[pid] = (total_ticks, now_mono)
        rss_sum_kb += (st["rss_pages"] * pg) / 1024.0

    # Drop cache entries for processes that have exited, so a pid-reuse
    # later in the run does not see a stale baseline.
    for stale in [p for p in _PER_PID if p not in seen_pids]:
        del _PER_PID[stale]

    return {
        "cpu_util": util,
        "cpu_util_present": util is not None,
        "load1": load1,
        "load5": load5,
        "load15": load15,
        "mem_total_kb": mem_total_kb,
        "mem_used_kb": mem_used_kb,
        "mem_available_kb": mem_avail_kb,
        "main_pids_live": n_live,
        "main_cpu_sum_pct": cpu_rate_sum * 100.0,   # percent of one core per pid, summed
        "main_rss_sum_kb": rss_sum_kb,
        "cpu_ram_present": totals is not None,
    }
