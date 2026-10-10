from __future__ import annotations
import time

from harness.src.metrics import ctx_switch
from harness.src.metrics._proc import proc_stat_totals


def _reset():
    ctx_switch._LAST = None
    ctx_switch._LAST_T = None


def test_first_call_has_no_rate():
    _reset()
    out = ctx_switch.collect(sample_interval=0.5)
    assert out["ctx_switch_present"] is True
    assert out["ctxt_total"] is not None
    assert out["ctxt_hz"] is None


def test_second_call_yields_strictly_positive_rate():
    """Under any real workload the system makes context switches. A metric
    that returns 0 or None on the second sample is broken.

    Sleep long enough that the /proc/stat ctxt counter must have advanced.
    On a truly idle machine this could theoretically be zero, so we spin
    for a moment to guarantee at least some scheduling activity."""
    _reset()
    ctx_switch.collect(sample_interval=0.5)
    # Force the scheduler to run: yield several times.
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        time.sleep(0.001)
    out = ctx_switch.collect(sample_interval=0.5)
    assert out["ctx_switch_present"] is True
    assert out["ctxt_hz"] is not None
    assert out["ctxt_hz"] > 0.0, f"expected > 0, got {out['ctxt_hz']}"


def test_total_is_monotonic():
    _reset()
    a = ctx_switch.collect(sample_interval=0.5)["ctxt_total"]
    time.sleep(0.1)
    b = ctx_switch.collect(sample_interval=0.5)["ctxt_total"]
    assert a is not None and b is not None
    assert b >= a


def test_proc_stat_totals_shape():
    totals = proc_stat_totals()
    assert totals is not None
    for k in ("user", "nice", "system", "idle", "iowait", "ctxt"):
        assert k in totals
