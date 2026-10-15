"""Count user-space background processes, excluding:
  * main task PIDs (and their descendants, since those are workloads)
  * the runner's own process tree
  * kernel threads (heuristic)

Kernel-thread heuristic: PPID == 2 (kthreadd), or the process has no
resident set (RSS == 0) and its parent is PID 1 or 2 and it has no
associated /proc/<pid>/cmdline. We keep this conservative: prefer to
under-count background rather than over-count, because over-counting
would drown out the actual workload signal.
"""
from __future__ import annotations

import pathlib
import os
from typing import Iterable

from ._proc import PROC, pid_stat, read_text


def _is_kernel_thread(pid: int) -> bool:
    st = pid_stat(pid)
    if st is None:
        return False
    # PPID == 2 is kthreadd's child on Linux.
    if st["ppid"] == 2:
        return True
    # Kernel threads have empty cmdline and RSS == 0.
    cmdline = read_text(PROC / str(pid) / "cmdline")
    if cmdline == "" and st["rss_pages"] == 0:
        return True
    return False


def _walker_ancestors(pid: int) -> set[int]:
    """Return pid and all its ancestors (up to PID 1)."""
    seen: set[int] = set()
    current = pid
    while current > 1 and current not in seen:
        seen.add(current)
        st = pid_stat(current)
        if st is None:
            break
        current = st["ppid"]
    return seen


def collect(excluded_pids: Iterable[int], *, proc_root: pathlib.Path = PROC) -> dict:
    """Count background user-space processes.

    excluded_pids should include every PID that the harness considers
    'ours' the workload root PIDs and their descendants. The runner's
    own ancestors are excluded automatically.
    """
    excluded = set(excluded_pids)
    excluded |= _walker_ancestors(os.getpid())

    count = 0
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return {"procbg_count": None, "procbg_present": False}
    for entry in entries:
        if not entry.is_dir() or not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in excluded:
            continue
        if _is_kernel_thread(pid):
            continue
        count += 1
    return {"procbg_count": count, "procbg_present": True}
