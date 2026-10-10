"""NVIDIA GPU metrics via nvidia-smi. If unavailable, returns a record
with gpu_present=False and zero process attribution; never raises."""
from __future__ import annotations

import csv
import io
import shutil
import subprocess
from typing import Iterable


NVIDIA_SMI = "nvidia-smi"
_QUERY = "index,utilization.gpu,memory.used,memory.total"


def is_available() -> bool:
    return shutil.which(NVIDIA_SMI) is not None


def _query() -> list[dict] | None:
    try:
        r = subprocess.run(
            [NVIDIA_SMI,
             f"--query-gpu={_QUERY}",
             "--format=csv,noheader,nounits"],
            check=False, capture_output=True, text=True,
        )
    except OSError:
        return None
    if r.returncode != 0:
        return None
    out = []
    for row in csv.reader(io.StringIO(r.stdout)):
        if len(row) < 4:
            continue
        try:
            out.append({
                "index": int(row[0].strip()),
                "util_pct": float(row[1].strip()),
                "mem_used_mb": float(row[2].strip()),
                "mem_total_mb": float(row[3].strip()),
            })
        except ValueError:
            continue
    return out


def collect(main_pids: Iterable[int], *, sample_interval: float) -> dict:
    if not is_available():
        return {
            "gpu_present": False,
            "gpu_count": 0,
            "gpu_util_max_pct": None,
            "gpu_mem_used_mb_sum": None,
            "gpu_mem_total_mb_sum": None,
        }
    gpus = _query()
    if gpus is None:
        return {
            "gpu_present": False,
            "gpu_count": 0,
            "gpu_util_max_pct": None,
            "gpu_mem_used_mb_sum": None,
            "gpu_mem_total_mb_sum": None,
        }
    util_max = max((g["util_pct"] for g in gpus), default=None)
    used_sum = sum(g["mem_used_mb"] for g in gpus)
    total_sum = sum(g["mem_total_mb"] for g in gpus)
    return {
        "gpu_present": True,
        "gpu_count": len(gpus),
        "gpu_util_max_pct": util_max,
        "gpu_mem_used_mb_sum": used_sum,
        "gpu_mem_total_mb_sum": total_sum,
    }
