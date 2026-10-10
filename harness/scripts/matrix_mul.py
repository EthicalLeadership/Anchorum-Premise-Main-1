#!/usr/bin/env python3
"""Matrix-multiplication workload. Stdlib only.

Simulates a dense compute workload for benchmarking purposes. Uses a
naive O(n^3) matmul with float arithmetic; no numpy dependency.
"""
from __future__ import annotations
import argparse, random, sys, time


def matmul(a, b):
    n = len(a)
    m = len(b[0])
    k = len(b)
    out = [[0.0] * m for _ in range(n)]
    for i in range(n):
        ai = a[i]
        oi = out[i]
        for p in range(k):
            aip = ai[p]
            bp = b[p]
            for j in range(m):
                oi[j] += aip * bp[j]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--size", type=int, default=64)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)
    a = [[rng.random() for _ in range(args.size)] for _ in range(args.size)]
    b = [[rng.random() for _ in range(args.size)] for _ in range(args.size)]

    deadline = time.monotonic() + args.seconds
    iterations = 0
    while time.monotonic() < deadline:
        a = matmul(a, b)
        # Renormalize to avoid overflow in long runs.
        s = a[0][0] or 1.0
        a = [[x / s for x in row] for row in a]
        iterations += 1

    print(f"matrix_mul: {iterations} iterations of {args.size}x{args.size}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
