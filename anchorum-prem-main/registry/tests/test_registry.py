"""Comprehensive pytest suite for the registry package."""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any, Coroutine, List, TypeVar

import pytest

import registry
from registry import (
    AuditEventPublishError,
    AWSSecretsManager,
    KeyRotationOrchestrator,
    KeyRotationService,
    KeyVersion,
    RotationError,
    RotationEvent,
    RotationState,
    SecretManager,
    VaultSecretManager,
    ZarcJournal,
    __version__,
)

T = TypeVar("T")
REPO_ROOT = Path(__file__).resolve().parents[1]


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Execute an async coroutine cleanly in sync pytest tests."""
    return asyncio.run(coro)


class FakeClock:
    """Deterministic nanosecond clock helper with independent instance state."""

    def __init__(self, start_ns: int = 1_000_000_000, step_ns: int = 10_000) -> None:
        self.current = start_ns
        self.step = step_ns

    def __call__(self) -> int:
        value = self.current
        self.current += self.step
        return value

    def set(self, value_ns: int) -> None:
        self.current = value_ns


class FakeEventBus:
    """In-memory event bus recording published RotationEvents."""

    def __init__(self, fail_publish: bool = False) -> None:
        self.events: List[RotationEvent] = []
        self.fail_publish = fail_publish

    async def publish(self, event: RotationEvent) -> None:
        if self.fail_publish:
            raise RuntimeError("simulated event bus outage")
        self.events.append(event)


class FailingHistorySecretManager(VaultSecretManager):
    """Test double that fails when retrieving key history."""

    async def get_key_history(self) -> List[KeyVersion]:
        raise ConnectionError("backing store unavailable")


class NonCompletingRotationManager(VaultSecretManager):
    """Test double that returns a non-completed RotationState."""

    async def rotate_keys(
        self,
        new_private_key_ref: str,
        new_public_key: bytes,
    ) -> RotationState:
        return RotationState(
            current_key_id="root-0",
            new_key_id="rotated-pending",
            predecessor_key_id="root-0",
            status="in_progress",
            error_message="awaiting quorum approval",
        )


@pytest.fixture(autouse=True)
def reset_zarc_default_clock() -> Any:
    """Reset class-level ZarcJournal clock state after every test."""
    yield
    ZarcJournal.set_default_clock(None)


def test_import_in_fresh_process_has_zero_clock_calls() -> None:
    """Importing registry and submodules must not invoke time.monotonic_ns."""
    code = (
        "import sys, time\n"
        "calls = 0\n"
        "orig = time.monotonic_ns\n"
        "def spy():\n"
        "    global calls\n"
        "    calls += 1\n"
        "    return orig()\n"
        "time.monotonic_ns = spy\n"
        "import registry\n"
        "import registry.zarc_journal\n"
        "import registry.vault_secret_manager\n"
        "import registry.key_rotation_service\n"
        "assert calls == 0, f'Expected 0 clock calls on import, got {calls}'\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"Subprocess failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"


def test_package_public_api_and_inheritance() -> None:
    assert isinstance(__version__, str) and len(__version__) > 0
    assert "__version__" in registry.__all__
    for symbol in registry.__all__:
        assert hasattr(registry, symbol), f"Exported symbol missing from registry: {symbol}"

    assert issubclass(VaultSecretManager, SecretManager)
    assert issubclass(AWSSecretsManager, SecretManager)


def test_zarc_journal_monotonic_clock_chain_hash_and_isolation() -> None:
    clock = FakeClock(start_ns=500_000, step_ns=1_000)
    ZarcJournal.set_default_clock(clock)

    t1 = ZarcJournal.now_ns()
    t2 = ZarcJournal.now_ns()
    assert t2 > t1

    # Stepping the underlying clock backward must not produce a decreasing timestamp.
    clock.set(100)
    t3 = ZarcJournal.now_ns()
    assert t3 >= t2

    journal = ZarcJournal(clock_ns=FakeClock(start_ns=2_000_000, step_ns=5_000))
    h1 = ZarcJournal.compute_chain_hash(None, b"root-pub", "")
    rec1 = journal.record("root-0", b"root-pub", predecessor_key_id=None, previous_chain_hash="")
    assert rec1.sequence == 1
    assert rec1.timestamp_ns == 2_000_000
    assert rec1.chain_hash == h1

    h2 = ZarcJournal.compute_chain_hash("root-0", b"key-v1", h1)
    rec2 = journal.record("key-v1", b"key-v1", predecessor_key_id="root-0", previous_chain_hash=h1)
    assert rec2.sequence == 2
    assert rec2.timestamp_ns == 2_005_000
    assert rec2.chain_hash == h2
    assert rec2.chain_hash != rec1.chain_hash

    history_copy = journal.get_key_history()
    assert len(history_copy) == 2
    history_copy.clear()
    assert len(journal.get_key_history()) == 2


@pytest.mark.parametrize(
    "manager_factory",
    [
        lambda: VaultSecretManager(
            vault_address="https://vault.local:8200",
            token="s.test-token",
            clock_ns=FakeClock(start_ns=10_000_000, step_ns=50_000),
        ),
        lambda: AWSSecretsManager(
            region_name="us-east-1",
            secret_id="anchorum-prem/trust-anchor",
            clock_ns=FakeClock(start_ns=20_000_000, step_ns=50_000),
        ),
    ],
)
def test_backends_rotation_and_chain_verification(manager_factory: Any) -> None:
    async def _case() -> None:
        manager: SecretManager = manager_factory()

        root = await manager.initialize_trust_anchor(b"root-public-key")
        assert root.key_id == "root-0"
        assert root.predecessor_key_id is None
        assert await manager.verify_signature_chain("root-0", expected_predecessor=None) is True

        rot1 = await manager.rotate_keys("kms://key-1", b"pub-key-1")
        assert isinstance(rot1, RotationState)
        assert rot1.status == "completed"
        assert rot1.current_key_id == "root-0"
        assert rot1.new_key_id is not None

        rot2 = await manager.rotate_keys("kms://key-2", b"pub-key-2")
        assert rot2.status == "completed"
        assert rot2.current_key_id == rot1.new_key_id
        assert rot2.new_key_id is not None

        v2 = await manager.get_current_key_version()
        assert v2 is not None
        assert v2.key_id == rot2.new_key_id
        assert v2.predecessor_key_id == rot1.new_key_id

        assert await manager.verify_signature_chain(v2.key_id, expected_predecessor=rot1.new_key_id) is True
        assert await manager.verify_signature_chain(v2.key_id, expected_predecessor="wrong-pred") is False
        assert await manager.verify_signature_chain("missing-key", expected_predecessor=None) is False

        history = await manager.get_key_history()
        assert [k.key_id for k in history] == ["root-0", rot1.new_key_id, rot2.new_key_id]
        history.clear()
        assert len(await manager.get_key_history()) == 3

    run_async(_case())


def test_key_rotation_service_chain_events_rollback_and_validation() -> None:
    async def _case() -> None:
        manager = VaultSecretManager(
            vault_address="https://vault.local:8200",
            token="s.test-token",
            clock_ns=FakeClock(start_ns=100_000_000, step_ns=10_000),
        )
        bus = FakeEventBus()
        service = KeyRotationService(
            secret_manager=manager,
            event_bus=bus,
            clock_ns=FakeClock(start_ns=200_000_000, step_ns=10_000),
        )

        with pytest.raises(ValueError):
            await service.initiate_rotation("", b"valid-pub")
        with pytest.raises(ValueError):
            await service.initiate_rotation("hsm://slot-1", b"")

        await manager.initialize_trust_anchor(b"root-key")
        rot1 = await service.initiate_rotation("hsm://slot-1", b"pub-1")
        rot2 = await service.initiate_rotation("hsm://slot-2", b"pub-2")

        assert len(bus.events) == 2
        ev1, ev2 = bus.events[0], bus.events[1]
        assert ev1.event_type == "KEY_ROTATION_COMPLETED"
        assert ev1.created_at_ns == ev1.payload["timestamp_ns"]
        assert ev1.previous_event_hash == ""

        expected_ev1_digest = hashlib.sha256(
            f"{ev1.stable_event_id}:{ev1.created_at_ns}:{ev1.signature}".encode("utf-8")
        ).hexdigest()
        assert ev2.previous_event_hash == expected_ev1_digest
        assert ev2.payload["predecessor_key_id"] == rot1.new_key_id

        assert await service.verify_key_chain_integrity(rot1.new_key_id, "root-0") is True
        assert await service.verify_key_chain_integrity("", "root-0") is False

        history_dicts = await service.get_key_history()
        assert len(history_dicts) == 3
        history_dicts.clear()
        assert len(await service.get_key_history()) == 3

        assert rot2.new_key_id is not None
        with pytest.raises(NotImplementedError):
            await service.rollback_to_predecessor(rot2.new_key_id)

        with pytest.raises(LookupError):
            await service.rollback_to_predecessor("does-not-exist")

        manager._key_history[1].signature_chain_hash = "tampered-hash"
        with pytest.raises(RotationError):
            await service.rollback_to_predecessor(rot2.new_key_id)

        failing_service = KeyRotationService(
            secret_manager=manager,
            event_bus=FakeEventBus(fail_publish=True),
            clock_ns=FakeClock(start_ns=300_000_000, step_ns=10_000),
        )
        with pytest.raises(AuditEventPublishError):
            await failing_service.initiate_rotation("hsm://slot-3", b"pub-3")

    run_async(_case())


def test_non_completing_rotation_and_orchestrator_error_paths() -> None:
    async def _case() -> None:
        non_completing_mgr = NonCompletingRotationManager(
            vault_address="https://vault.local:8200",
            token="s.test-token",
            clock_ns=FakeClock(start_ns=400_000_000, step_ns=10_000),
        )
        bus = FakeEventBus()
        service = KeyRotationService(
            secret_manager=non_completing_mgr,
            event_bus=bus,
            clock_ns=FakeClock(start_ns=500_000_000, step_ns=10_000),
        )

        with pytest.raises(RotationError):
            await service.initiate_rotation("hsm://slot-pending", b"pub-pending")

        assert len(bus.events) == 1
        assert bus.events[0].event_type == "KEY_ROTATION_FAILED"

        orchestrator = KeyRotationOrchestrator(
            secret_manager=non_completing_mgr,
            event_bus=FakeEventBus(),
            clock_ns=FakeClock(start_ns=600_000_000, step_ns=10_000),
        )
        failed_res = await orchestrator.rotate_keys("hsm://slot-pending", b"pub-pending")
        assert failed_res["status"] == "failed"
        assert "error" in failed_res

        broken_mgr = FailingHistorySecretManager(
            vault_address="https://vault.local:8200",
            token="s.test-token",
        )
        broken_service = KeyRotationService(secret_manager=broken_mgr)
        with pytest.raises(ConnectionError):
            await broken_service.get_key_history()

        broken_orchestrator = KeyRotationOrchestrator(secret_manager=broken_mgr)
        status_res = await broken_orchestrator.get_status()
        assert status_res["status"] == "error"
        assert "error" in status_res

    run_async(_case())
