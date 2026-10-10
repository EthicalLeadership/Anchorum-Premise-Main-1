#!/usr/bin/env python3
"""Disk write workload: MB/s sustained writes to a temp file."""
from __future__ import annotations
import argparse, os, sys, tempfile, time


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--mb-per-sec", type=float, default=50.0)
    args = ap.parse_args(argv)

    block = b"\x00" * (1024 * 1024)
    bytes_per_sec = int(args.mb_per_sec * 1024 * 1024)
    deadline = time.monotonic() + args.seconds
    written = 0

    fd, path = tempfile.mkstemp(prefix="audit_diskwrite_", suffix=".bin")
    try:
        with os.fdopen(fd, "wb") as f:
            window_start = time.monotonic()
            window_bytes = 0
            while time.monotonic() < deadline:
                f.write(block)
                window_bytes += len(block)
                written += len(block)
                now = time.monotonic()
                window = now - window_start
                if window >= 0.1:
                    target = bytes_per_sec * window
                    if window_bytes < target:
                        time.sleep((target - window_bytes) / bytes_per_sec)
                    window_start = now
                    window_bytes = 0
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    print(f"disk_writer: {written // (1024*1024)} MB written", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
