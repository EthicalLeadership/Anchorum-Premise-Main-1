"""Main-task classification.

Two paths:

  1. Lane Op, if present, maps workload root PIDs to the set of PIDs
     considered 'main' tasks (e.g., excluding watcher threads, prefetch
     workers, logging helpers).

  2. Fallback, always available: walk /proc/<pid>/task/ and /proc/<pid>/stat
     to collect the process and all its descendants. Treat every
     descendant as a main task. This over-counts when a workload spawns
     helper processes; it never under-counts.

The fallback is the primary path in this repository because no laneop
module is present. See module docstring of harness/__init__.py.
"""
from __future__ import annotations

import pathlib
from typing import Iterable


def _read_int(path: pathlib.Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _ppid(pid: int, proc_root: pathlib.Path) -> int | None:
    """Return the parent PID from /proc/<pid>/stat. Returns None on any
    read or parse error, including processes that vanished mid-scan."""
    stat_path = proc_root / str(pid) / "stat"
    try:
        line = stat_path.read_text()
    except OSError:
        return None
    # Field 4 (1-indexed) is PPID. The comm field (field 2) is in parens
    # and can contain spaces and ')'. Find the LAST ')' to be safe.
    close = line.rfind(")")
    if close == -1:
        return None
    rest = line[close + 2:].split()
    # rest[0] is state (field 3), rest[1] is ppid (field 4)
    if len(rest) < 2:
        return None
    try:
        return int(rest[1])
    except ValueError:
        return None


def _all_pids(proc_root: pathlib.Path) -> list[int]:
    out = []
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return out
    for entry in entries:
        if not entry.is_dir():
            continue
        name = entry.name
        if not name.isdigit():
            continue
        out.append(int(name))
    return out


def descendants(root_pids: Iterable[int],
                proc_root: pathlib.Path = pathlib.Path("/proc")) -> set[int]:
    """Return root_pids plus every descendant of every root pid.

    Deterministic: reads /proc once to build the parent map, then walks it.
    If a PID disappears during the scan, it is silently skipped — the
    caller gets the set of live descendants at scan time.
    """
    roots = set(root_pids)
    parent_of: dict[int, int] = {}
    for pid in _all_pids(proc_root):
        ppid = _ppid(pid, proc_root)
        if ppid is not None:
            parent_of[pid] = ppid

    children: dict[int, list[int]] = {}
    for pid, ppid in parent_of.items():
        children.setdefault(ppid, []).append(pid)

    seen: set[int] = set()
    stack = list(roots)
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        stack.extend(children.get(pid, []))
    return seen


def classify_main_tasks(root_pids: Iterable[int]) -> set[int]:
    """Classify main task PIDs.

    Attempts to import a `laneop` module; if present, delegates. Otherwise
    falls back to descendants(). The fallback treats all descendants of
    the workload as main tasks.
    """
    try:
        import laneop as _laneop  # type: ignore
    except ImportError:
        return descendants(root_pids)
    # If a laneop module appears later, its classify_main_tasks() is used.
    fn = getattr(_laneop, "classify_main_tasks", None)
    if fn is None:
        return descendants(root_pids)
    return set(fn(set(root_pids)))
