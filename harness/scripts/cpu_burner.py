#!/usr/bin/env python3
"""CPU burner: N processes spinning on a tight arithmetic loop."""
from __future__ import annotations
import argparse, multiprocessing as mp, sys, time


def _spin(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    x = 0
    while time.monotonic() < deadline:
        for _ in range(10000):
            x = (x * 1103515245 + 12345) & 0x7FFFFFFF


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args(argv)

    procs = [mp.Process(target=_spin, args=(args.seconds,)) for _ in range(args.workers)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    print(f"cpu_burner: {args.workers} workers done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
