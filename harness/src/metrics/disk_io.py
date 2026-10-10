"""Disk I/O from /proc/diskstats.

We do NOT parse iostat -x: its output format is not stable across
versions and locales. /proc/diskstats is stable and gives us bytes read,
bytes written, and I/O time per device; we compute per-device rates from
the delta since the previous sample. %util is approximated as
io_time_delta_ms / (sample_interval * 1000) per device.

Sectors are 512 bytes (kernel convention, unchanged since 2.4)."""
from __future__ import annotations

import pathlib

from ._proc import PROC, read_text


SECTOR_BYTES = 512
_LAST: dict[str, dict] | None = None
_LAST_T: float | None = None


def _parse_diskstats(raw: str) -> dict[str, dict]:
    """Parse /proc/diskstats into {device: counters}.

    Field layout (1-indexed per the kernel docs):
      1 major, 2 minor, 3 name,
      4 reads completed, 5 reads merged, 6 sectors read, 7 ms reading,
      8 writes completed, 9 writes merged, 10 sectors written, 11 ms writing,
      12 ios in progress, 13 ms doing io, 14 weighted ms io
    """
    out: dict[str, dict] = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 14:
            continue
        name = parts[2]
        try:
            out[name] = {
                "reads_completed": int(parts[3]),
                "sectors_read": int(parts[5]),
                "ms_reading": int(parts[6]),
                "writes_completed": int(parts[7]),
                "sectors_written": int(parts[9]),
                "ms_writing": int(parts[10]),
                "ios_in_progress": int(parts[11]),
                "ms_io": int(parts[12]),
            }
        except (ValueError, IndexError):
            continue
    return out


def collect(*, sample_interval: float,
            devices: tuple[str, ...] | None = None) -> dict:
    """Return disk I/O metrics.

    If `devices` is None, aggregate across all non-partition devices
    matching the pattern of a top-level device (heuristic: name does not
    end in a digit, OR is 'dm-<n>' OR 'nvme<n>n<digits>'). We do not
    attempt to detect partitioning from sysfs; the aggregate across all
    devices is what we report by default.
    """
    global _LAST, _LAST_T
    import time
    now_t = time.monotonic()
    raw = read_text(PROC / "diskstats")
    if raw is None:
        return {"disk_read_bps": None, "disk_write_bps": None,
                "disk_util": None, "disk_io_present": False}
    current = _parse_diskstats(raw)

    out = {
        "disk_read_bps": None,
        "disk_write_bps": None,
        "disk_util": None,
        "disk_io_present": True,
    }
    if _LAST is not None and _LAST_T is not None:
        dt = now_t - _LAST_T
        if dt > 0:
            d_read = d_write = 0
            d_io_ms = 0
            for name, cur in current.items():
                prev = _LAST.get(name)
                if prev is None:
                    continue
                d_read += (cur["sectors_read"] - prev["sectors_read"]) * SECTOR_BYTES
                d_write += (cur["sectors_written"] - prev["sectors_written"]) * SECTOR_BYTES
                d_io_ms += (cur["ms_io"] - prev["ms_io"])
            out["disk_read_bps"] = d_read / dt
            out["disk_write_bps"] = d_write / dt
            # Aggregate %util-like metric: total io-ms across devices
            # divided by (interval_ms * n_devices). Reported as a fraction.
            n_dev = max(1, len([n for n in current if n in _LAST]))
            interval_ms = dt * 1000.0
            out["disk_util"] = d_io_ms / (interval_ms * n_dev) if interval_ms else None

    _LAST = current
    _LAST_T = now_t
    return out
