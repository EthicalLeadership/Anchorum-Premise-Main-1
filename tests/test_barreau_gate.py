import hashlib

from barreau_gate import (
    BarreauCredential,
    BarreauGate,
    RegistryRecord,
    Status,
)


def fp(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class FakeRegistry:
    def __init__(self, records=None, raises=False):
        self._records = records or {}
        self._raises = raises

    def lookup(self, bar_id):
        if self._raises:
            raise RuntimeError("boom")
        return self._records.get(bar_id)


class FakeAudit:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)


GOOD_ID = "1234567"
GOOD_FP = fp("good")


def make_gate(**kw):
    audit = FakeAudit()
    registry = FakeRegistry({GOOD_ID: RegistryRecord(GOOD_ID, GOOD_FP, True)}, **kw)
    return BarreauGate(registry, audit), audit


def test_valid():
    gate, _ = make_gate()
    r = gate.validate(BarreauCredential(GOOD_ID, GOOD_FP), actor_id="admin1")
    assert r.ok and r.status == Status.VALID


def test_bad_bar_id_format():
    gate, _ = make_gate()
    r = gate.validate(BarreauCredential("bad id!", GOOD_FP), actor_id="admin1")
    assert not r.ok and r.status == Status.INVALID_FORMAT


def test_bad_fingerprint_format():
    gate, _ = make_gate()
    r = gate.validate(BarreauCredential(GOOD_ID, "nothex"), actor_id="admin1")
    assert not r.ok and r.status == Status.INVALID_FORMAT


def test_not_found():
    gate, _ = make_gate()
    r = gate.validate(BarreauCredential("9999999", GOOD_FP), actor_id="admin1")
    assert not r.ok and r.status == Status.NOT_FOUND


def test_fingerprint_mismatch():
    gate, _ = make_gate()
    r = gate.validate(BarreauCredential(GOOD_ID, fp("wrong")), actor_id="admin1")
    assert not r.ok and r.status == Status.FINGERPRINT_MISMATCH


def test_inactive():
    audit = FakeAudit()
    reg = FakeRegistry({GOOD_ID: RegistryRecord(GOOD_ID, GOOD_FP, False)})
    gate = BarreauGate(reg, audit)
    r = gate.validate(BarreauCredential(GOOD_ID, GOOD_FP), actor_id="admin1")
    assert not r.ok and r.status == Status.INACTIVE


def test_audit_omits_fingerprint():
    gate, audit = make_gate()
    gate.validate(BarreauCredential(GOOD_ID, GOOD_FP), actor_id="admin1")
    assert audit.events
    e = audit.events[-1]
    assert "fingerprint_hex" not in e and GOOD_FP not in str(e)


def test_registry_error():
    gate, _ = make_gate(raises=True)
    r = gate.validate(BarreauCredential(GOOD_ID, GOOD_FP), actor_id="admin1")
    assert not r.ok and r.status == Status.REGISTRY_ERROR


def test_registry_error():
    gate, _ = make_gate(raises=True)
    r = gate.validate(BarreauCredential(GOOD_ID, GOOD_FP), actor_id="admin1")
    assert not r.ok and r.status == Status.REGISTRY_ERROR
