"""System-wide context switch rate from /proc/stat 'ctxt'."""
from __future__ import annotations

from ._proc import proc_stat_totals


_LAST: dict | None = None
_LAST_T: float | None = None


def collect(*, sample_interval: float) -> dict:
    """Return context switch delta rate in Hz (switches per second)
    computed from the previous call. First call returns None for the rate
    and records the baseline."""
    global _LAST, _LAST_T
    import time
    now_t = time.monotonic()
    totals = proc_stat_totals()
    if totals is None:
        return {"ctxt_hz": None, "ctxt_total": None, "ctx_switch_present": False}
    ctxt = totals["ctxt"]
    rate = None
    if _LAST is not None and _LAST_T is not None:
        dt = now_t - _LAST_T
        if dt > 0:
            rate = (ctxt - _LAST["ctxt"]) / dt
    _LAST = totals
    _LAST_T = now_t
    return {
        "ctxt_hz": rate,
        "ctxt_total": ctxt,
        "ctx_switch_present": True,
    }
