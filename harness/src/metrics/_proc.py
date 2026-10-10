"""Shared /proc readers. Deterministic, stdlib-only, tolerant of races
(processes that vanish between listing and reading)."""
from __future__ import annotations

import pathlib
import time
from typing import Iterable

PROC = pathlib.Path("/proc")


def read_text(path: pathlib.Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def pid_stat(pid: int, proc_root: pathlib.Path = PROC) -> dict | None:
    """Parse /proc/<pid>/stat.

    Returns a dict with keys utime, stime, rss_pages, state, ppid.
    utime and stime are in clock ticks (USER_HZ, typically 100).
    rss is pages, multiply by page size for bytes.
    Returns None on any error.
    """
    raw = read_text(proc_root / str(pid) / "stat")
    if raw is None:
        return None
    close = raw.rfind(")")
    if close == -1:
        return None
    head, rest = raw[:close + 1], raw[close + 2:].split()
    if len(rest) < 22:
        return None
    try:
        state = rest[0]
        ppid = int(rest[1])
        utime = int(rest[11])   # field 14 (1-indexed)
        stime = int(rest[12])   # field 15
        rss_pages = int(rest[21])  # field 24
    except (ValueError, IndexError):
        return None
    return {
        "state": state,
        "ppid": ppid,
        "utime": utime,
        "stime": stime,
        "rss_pages": rss_pages,
    }


def page_size() -> int:
    import os
    return os.sysconf("SC_PAGE_SIZE")


def user_hz() -> int:
    import os
    return os.sysconf("SC_CLK_TCK")


def first_line(path: pathlib.Path) -> str | None:
    raw = read_text(path)
    if raw is None:
        return None
    return raw.splitlines()[0] if raw.splitlines() else None


def proc_stat_totals(proc_root: pathlib.Path = PROC) -> dict | None:
    """Return aggregate CPU tick totals and ctxt (cumulative context switches).
    Reads /proc/stat first line 'cpu' + the 'ctxt' line."""
    raw = read_text(proc_root / "stat")
    if raw is None:
        return None
    out: dict[str, int] = {}
    for line in raw.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "ctxt":
            try:
                out["ctxt"] = int(parts[1])
            except (ValueError, IndexError):
                return None
        elif parts[0] == "cpu":
            # user nice system idle iowait irq softirq steal guest guest_nice
            try:
                vals = [int(x) for x in parts[1:]]
            except ValueError:
                return None
            out["user"] = vals[0] if len(vals) > 0 else 0
            out["nice"] = vals[1] if len(vals) > 1 else 0
            out["system"] = vals[2] if len(vals) > 2 else 0
            out["idle"] = vals[3] if len(vals) > 3 else 0
            out["iowait"] = vals[4] if len(vals) > 4 else 0
            out["irq"] = vals[5] if len(vals) > 5 else 0
            out["softirq"] = vals[6] if len(vals) > 6 else 0
            out["steal"] = vals[7] if len(vals) > 7 else 0
    if "ctxt" not in out or "user" not in out:
        return None
    return out
