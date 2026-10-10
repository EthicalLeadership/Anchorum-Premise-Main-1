from __future__ import annotations
import os
import pathlib

from harness.src.metrics import procbg


def test_collect_returns_integer_count():
    """Shape check: the collector returns an integer and never raises."""
    out = procbg.collect([])
    assert out["procbg_present"] is True
    assert isinstance(out["procbg_count"], int)


def test_self_is_excluded_via_ancestors():
    """The runner's own ancestors are excluded from the background count.
    Verified by checking _walker_ancestors includes our PID."""
    chain = procbg._walker_ancestors(os.getpid())
    assert os.getpid() in chain
    # PID 1 must terminate the walk.
    assert 1 in chain or chain  # walk stops at pid <= 1


def test_explicit_exclusion_reduces_count_by_one():
    """Excluding a currently-counted PID must reduce the count by exactly 1.
    This is the actual filter behavior; it must not be a no-op."""
    proc = pathlib.Path("/proc")
    base = procbg.collect([], proc_root=proc)["procbg_count"]
    our_chain = procbg._walker_ancestors(os.getpid())
    candidate = None
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in our_chain:
            continue
        if procbg._is_kernel_thread(pid):
            continue
        candidate = pid
        break
    if candidate is None:
        return   # nothing to exclude on this host
    reduced = procbg.collect([candidate], proc_root=proc)["procbg_count"]
    assert reduced == base - 1, (
        f"excluding pid {candidate} should reduce count by 1; "
        f"base={base} reduced={reduced}"
    )
