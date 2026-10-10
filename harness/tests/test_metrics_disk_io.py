from __future__ import annotations
import os
import pathlib
import tempfile
import time

from harness.src.metrics import disk_io
from harness.src.metrics._proc import PROC, read_text


def _reset():
    disk_io._LAST = None
    disk_io._LAST_T = None


def test_diskstats_parser_accepts_real_file():
    """Parse the real /proc/diskstats and assert every counter is an int."""
    raw = read_text(PROC / "diskstats")
    assert raw is not None
    parsed = disk_io._parse_diskstats(raw)
    assert len(parsed) > 0
    for name, counters in parsed.items():
        for k in ("reads_completed", "sectors_read", "ms_reading",
                  "writes_completed", "sectors_written", "ms_writing", "ms_io"):
            assert isinstance(counters[k], int)


def test_first_sample_has_no_rate():
    _reset()
    out = disk_io.collect(sample_interval=0.5)
    assert out["disk_io_present"] is True
    assert out["disk_read_bps"] is None
    assert out["disk_write_bps"] is None


def test_write_actually_produces_positive_rate():
    """Force real disk I/O between the two samples and assert the write
    rate is strictly positive. A collector that silently returns 0 would
    fail this test."""
    _reset()
    disk_io.collect(sample_interval=0.5)
    with tempfile.NamedTemporaryFile(dir=pathlib.Path.cwd(), delete=False) as f:
        try:
            f.write(b"\x00" * (4 * 1024 * 1024))
            f.flush()
            os.fsync(f.fileno())
        finally:
            path = f.name
    try:
        time.sleep(0.2)
        out = disk_io.collect(sample_interval=0.5)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    assert out["disk_io_present"] is True
    assert out["disk_write_bps"] is not None
    # Kernel may have written to page cache only; still expect the delta
    # to be captured because fsync forced the write-through.
    assert out["disk_write_bps"] > 0.0, (
        f"expected positive write rate after 4 MiB fsync, "
        f"got {out['disk_write_bps']}"
    )
