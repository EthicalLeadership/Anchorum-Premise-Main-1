from __future__ import annotations

from harness.src.metrics import gpu


def test_no_gpu_returns_nulls_not_raises(monkeypatch):
    """If nvidia-smi is absent, collect() must not raise and must return
    gpu_present=False with null numeric fields."""
    monkeypatch.setattr(gpu.shutil, "which", lambda name: None)
    out = gpu.collect([], sample_interval=1.0)
    assert out["gpu_present"] is False
    assert out["gpu_count"] == 0
    assert out["gpu_util_max_pct"] is None
    assert out["gpu_mem_used_mb_sum"] is None


def test_gpu_present_path(monkeypatch):
    """Simulate nvidia-smi output; verify parsing."""
    monkeypatch.setattr(gpu.shutil, "which", lambda name: "/usr/bin/nvidia-smi")

    class FakeRun:
        returncode = 0
        stdout = "0, 42, 4096, 12288\n"
        stderr = ""

    monkeypatch.setattr(gpu.subprocess, "run", lambda *a, **k: FakeRun())
    out = gpu.collect([], sample_interval=1.0)
    assert out["gpu_present"] is True
    assert out["gpu_count"] == 1
    assert out["gpu_util_max_pct"] == 42.0
    assert out["gpu_mem_used_mb_sum"] == 4096.0
