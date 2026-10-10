"""Registry store (v3), audit chain, trace. Run: pytest tests/test_registry.py -v."""
import json
from pathlib import Path

import pytest

from dossier_pipeline.registry import keys as _keys
from dossier_pipeline.registry.entry import sign_entry, verify_entry, snapshot_hash
from dossier_pipeline.registry.store import (
    RegistryStore, RegistryError, DuplicateConfigHash, SignatureInvalid,
    SnapshotHashMismatch, RevokedSigner, UnauthorizedSigner, UnknownConfigHash,
)
from dossier_pipeline.registry.audit import AuditLog
from dossier_pipeline.registry.trace import TraceRecord, TraceLog
from dossier_pipeline.registry.trust import (
    Signer, build_anchor, revoke, rotate,
)


# ---------- fixtures -----------------------------------------------------

@pytest.fixture
def kd(tmp_path):
    return tmp_path / "keys"


@pytest.fixture
def root_kp(kd):
    return _keys.generate_keypair("anchorum-root", root=kd)


@pytest.fixture
def signer_kp(kd):
    return _keys.generate_keypair("test-signer", root=kd)


@pytest.fixture
def anchor(root_kp, signer_kp):
    """v3 genesis anchor with one root and one authorized signer."""
    return build_anchor(
        root_ids=("anchorum-root",),
        threshold=1,
        signers={
            signer_kp.signer_id: Signer(
                pubkey=signer_kp.public_key.public_bytes_raw().hex(),
                authorized_at="2026-01-01T00:00:00Z",
                revoked_at=None,
            ),
        },
        root_private_keys={"anchorum-root": root_kp.private_key},
        anchor_seq=0,
    )


@pytest.fixture
def root_pubkeys(root_kp):
    return {"anchorum-root": root_kp.public_key}


@pytest.fixture
def store(tmp_path, anchor, root_pubkeys):
    return RegistryStore(
        tmp_path / "registry.jsonl",
        trust_anchor=anchor,
        root_pubkeys=root_pubkeys,
    )


def _snap():
    return {"engine_version": "ccsp-3.3.0", "rules_hash": "abc123", "vertical": "legal"}


def _register(s, signer_kp, snapshot=None):
    snapshot = snapshot or _snap()
    ch = snapshot_hash(snapshot)
    entry = sign_entry(
        config_hash=ch, vertical_id="legal", engine_version="ccsp-3.3.0",
        config_snapshot=snapshot, private_key=signer_kp.private_key,
        signer_id=signer_kp.signer_id,
    )
    s.append(entry)
    return entry


# ---------- keys ---------------------------------------------------------

def test_key_generation_creates_both_files(signer_kp, kd):
    sid = signer_kp.signer_id
    assert (kd / f"{sid}.priv").exists()
    assert (kd / f"{sid}.pub").exists()


def test_key_generation_refuses_duplicate(tmp_path):
    _keys.generate_keypair("s1", root=tmp_path / "k")
    with pytest.raises(FileExistsError):
        _keys.generate_keypair("s1", root=tmp_path / "k")


# ---------- store: construction invariants -------------------------------

def test_store_requires_anchor(tmp_path, root_pubkeys):
    with pytest.raises(RegistryError):
        RegistryStore(tmp_path / "r.jsonl", root_pubkeys=root_pubkeys)  # noqa


def test_store_requires_root_pubkeys(tmp_path, anchor):
    with pytest.raises(RegistryError):
        RegistryStore(tmp_path / "r.jsonl", trust_anchor=anchor)  # noqa


def test_store_rejects_bad_anchor_signature(tmp_path, anchor, root_kp):
    """Constructing a store with pubkeys that don't verify the anchor fails."""
    wrong_pubkeys = {"anchorum-root": _keys.generate_keypair("other", root=tmp_path / "k").public_key}
    with pytest.raises(RegistryError):
        RegistryStore(tmp_path / "r.jsonl", trust_anchor=anchor, root_pubkeys=wrong_pubkeys)


# ---------- store: append ------------------------------------------------

def test_register_and_get(store, signer_kp):
    e = _register(store, signer_kp)
    got = store.get(e.config_hash)
    assert got.config_hash == e.config_hash
    assert got.vertical_id == "legal"


def test_duplicate_config_hash_rejected(store, signer_kp):
    _register(store, signer_kp)
    with pytest.raises(DuplicateConfigHash):
        _register(store, signer_kp)


def test_signature_tamper_rejected(store, signer_kp):
    snap = _snap()
    ch = snapshot_hash(snap)
    e = sign_entry(
        config_hash=ch, vertical_id="legal", engine_version="ccsp-3.3.0",
        config_snapshot=snap, private_key=signer_kp.private_key,
        signer_id=signer_kp.signer_id,
    )
    tampered = type(e)(
        config_hash=e.config_hash, vertical_id=e.vertical_id,
        engine_version=e.engine_version,
        config_snapshot={**e.config_snapshot, "rules_hash": "evil"},
        signed_at=e.signed_at, signer_id=e.signer_id, signature=e.signature,
    )
    with pytest.raises((SignatureInvalid, SnapshotHashMismatch)):
        store.append(tampered)


def test_snapshot_hash_mismatch_rejected(store, signer_kp):
    snap = _snap()
    bad = sign_entry(
        config_hash="0" * 64, vertical_id="legal", engine_version="ccsp-3.3.0",
        config_snapshot=snap, private_key=signer_kp.private_key,
        signer_id=signer_kp.signer_id,
    )
    with pytest.raises(SnapshotHashMismatch):
        store.append(bad)


def test_append_rejects_signer_not_in_anchor(tmp_path, anchor, root_pubkeys, kd):
    """A store whose anchor doesn't list this signer rejects its entries."""
    stranger = _keys.generate_keypair("stranger", root=kd)
    s = RegistryStore(tmp_path / "r.jsonl", trust_anchor=anchor, root_pubkeys=root_pubkeys)
    with pytest.raises(UnauthorizedSigner):
        _register(s, stranger)


def test_verify_all_clean(store, signer_kp):
    _register(store, signer_kp)
    assert store.verify_all() == []


def test_get_unknown_raises(store):
    with pytest.raises(UnknownConfigHash):
        store.get("nope")


def test_e2e_register_then_verify(store, signer_kp):
    e = _register(store, signer_kp)
    got = store.get(e.config_hash)
    assert got.config_snapshot == e.config_snapshot
    pub = signer_kp.public_key
    assert verify_entry(got, pub)


# ---------- store: revocation via anchor (Design D) ----------------------

def test_revoked_signer_rejected_via_anchor(tmp_path, anchor, root_pubkeys,
                                            root_kp, signer_kp):
    """Revoking the signer means producing a new anchor; a store built
    with that new anchor (and its predecessor) rejects new appends."""
    revoked_anchor = revoke(
        old_anchor=anchor,
        signer_id=signer_kp.signer_id,
        root_id="anchorum-root",
        root_private_key=root_kp.private_key,
    )
    s = RegistryStore(
        tmp_path / "r.jsonl",
        trust_anchor=revoked_anchor,
        root_pubkeys=root_pubkeys,
        predecessor=anchor,
    )
    with pytest.raises(RevokedSigner):
        _register(s, signer_kp)


def test_verify_all_reports_revoked_signer(tmp_path, anchor, root_pubkeys,
                                           root_kp, signer_kp):
    """An entry signed before revocation is flagged by verify_all under
    the revoked anchor."""
    # First register under the original anchor.
    s_before = RegistryStore(
        tmp_path / "r.jsonl",
        trust_anchor=anchor,
        root_pubkeys=root_pubkeys,
    )
    e = _register(s_before, signer_kp)

    # Now revoke and re-open the same file with the revoked anchor.
    revoked_anchor = revoke(
        old_anchor=anchor,
        signer_id=signer_kp.signer_id,
        root_id="anchorum-root",
        root_private_key=root_kp.private_key,
    )
    s_after = RegistryStore(
        tmp_path / "r.jsonl",
        trust_anchor=revoked_anchor,
        root_pubkeys=root_pubkeys,
        predecessor=anchor,
    )
    errors = s_after.verify_all()
    assert any(err[0] == e.config_hash for err in errors), errors
    assert any("revoked" in msg for _, msg in errors), errors


def test_new_store_accepts_rotation_with_predecessor(tmp_path, anchor,
                                                     root_pubkeys, root_kp):
    """A caller can rotate the root set and construct a new store with the
    rotated anchor, provided they supply the predecessor."""
    rotated = rotate(
        old_anchor=anchor,
        new_root_ids=("anchorum-root",),
        new_threshold=1,
        root_private_keys={"anchorum-root": root_kp.private_key},
    )
    s = RegistryStore(
        tmp_path / "r.jsonl",
        trust_anchor=rotated,
        root_pubkeys=root_pubkeys,
        predecessor=anchor,
    )
    assert s.anchor.anchor_seq == anchor.anchor_seq + 1


def test_store_rejects_rotation_without_predecessor(tmp_path, anchor,
                                                    root_pubkeys, root_kp):
    """Without a predecessor, a rotation anchor is treated as genesis and
    rejected (rotation_of must be None for genesis)."""
    rotated = rotate(
        old_anchor=anchor,
        new_root_ids=("anchorum-root",),
        new_threshold=1,
        root_private_keys={"anchorum-root": root_kp.private_key},
    )
    with pytest.raises(RegistryError):
        RegistryStore(
            tmp_path / "r.jsonl",
            trust_anchor=rotated,
            root_pubkeys=root_pubkeys,
        )


# ---------- audit --------------------------------------------------------

def test_audit_append_and_verify(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append({"projection_id": "a"})
    log.append({"projection_id": "b"})
    assert log.verify_chain() == []


def test_audit_detects_record_tampering(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append({"x": 1}); log.append({"x": 2})
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    d = json.loads(lines[0]); d["record"] = {"x": 999}
    lines[0] = json.dumps(d, sort_keys=True, separators=(",", ":"))
    (tmp_path / "audit.jsonl").write_text("\n".join(lines) + "\n")
    errors = log.verify_chain()
    assert any("record_hash" in e[1] for e in errors)


def test_audit_detects_chain_break(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append({"x": 1}); log.append({"x": 2}); log.append({"x": 3})
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    lines.pop(1)
    (tmp_path / "audit.jsonl").write_text("\n".join(lines) + "\n")
    errors = log.verify_chain()
    assert errors


# ---------- trace --------------------------------------------------------

def test_trace_id_deterministic():
    r1 = TraceRecord.build(vertical_id="legal", projection_ids=("p1", "p2"),
                           decision={"route": "PASS"}, config_hash="c" * 64)
    r2 = TraceRecord.build(vertical_id="legal", projection_ids=("p1", "p2"),
                           decision={"route": "PASS"}, config_hash="c" * 64)
    assert r1.trace_id == r2.trace_id


def test_trace_id_changes_with_input():
    r1 = TraceRecord.build(vertical_id="legal", projection_ids=("p1",),
                           decision={"route": "PASS"}, config_hash="c" * 64)
    r2 = TraceRecord.build(vertical_id="legal", projection_ids=("p1",),
                           decision={"route": "FAIL"}, config_hash="c" * 64)
    assert r1.trace_id != r2.trace_id


def test_trace_log_roundtrip(tmp_path):
    log = TraceLog(tmp_path / "trace.jsonl")
    r = TraceRecord.build(vertical_id="legal", projection_ids=("p1",),
                          decision={"route": "PASS"}, config_hash="c" * 64)
    log.append(r)
    got = list(log)
    assert len(got) == 1
    assert got[0].trace_id == r.trace_id
    assert got[0].projection_ids == ("p1",)


def test_trace_find_by_projection(tmp_path):
    log = TraceLog(tmp_path / "trace.jsonl")
    r1 = TraceRecord.build(vertical_id="legal", projection_ids=("p1",),
                           decision={"route": "PASS"}, config_hash="c" * 64)
    r2 = TraceRecord.build(vertical_id="legal", projection_ids=("p2",),
                           decision={"route": "FAIL"}, config_hash="c" * 64)
    log.append(r1); log.append(r2)
    found = log.find_by_projection("p1")
    assert len(found) == 1 and found[0].trace_id == r1.trace_id


# ---------- keys path traversal + permissions ---------------------------

def test_generate_keypair_rejects_path_traversal(tmp_path):
    kr = tmp_path / "keys"
    outside = tmp_path / "escaped.priv"
    with pytest.raises((ValueError, FileExistsError, OSError)):
        _keys.generate_keypair("../escaped", root=kr)
    assert not outside.exists(), "path traversal wrote outside key directory"


def test_generate_keypair_rejects_absolute_path(tmp_path):
    kr = tmp_path / "keys"
    with pytest.raises((ValueError, OSError)):
        _keys.generate_keypair("/tmp/anch_escape", root=kr)
    assert not Path("/tmp/anch_escape.priv").exists()


def test_key_dir_is_0700(tmp_path):
    kr = tmp_path / "keys"
    _keys.generate_keypair("owner-only", root=kr)
    mode = kr.stat().st_mode & 0o777
    assert mode == 0o700, f"key dir mode is {oct(mode)}, expected 0o700"


def test_private_key_is_0600(tmp_path):
    kr = tmp_path / "keys"
    _keys.generate_keypair("perm-check", root=kr)
    priv = kr / "perm-check.priv"
    mode = priv.stat().st_mode & 0o777
    assert mode == 0o600, f"private key mode is {oct(mode)}, expected 0o600"


# ---------- S1: concurrent append ----------------------------------------

def _concurrent_duplicate_worker(entry, anchor_path_str, pubkeys_path_str,
                                 reg_path_str, barrier, result_q):
    """S1 worker. Reconstructs the store from on-disk artifacts so the
    process is picklable under multiprocessing 'spawn'."""
    from pathlib import Path
    from dossier_pipeline.registry.store import RegistryStore
    from dossier_pipeline.registry.trust import load_anchor, root_pubkeys_from_file
    anchor = load_anchor(path=Path(anchor_path_str))
    pubkeys = root_pubkeys_from_file(Path(pubkeys_path_str))
    s = RegistryStore(
        Path(reg_path_str),
        trust_anchor=anchor,
        root_pubkeys=pubkeys,
    )
    barrier.wait()
    try:
        s.append(entry)
        result_q.put("ok")
    except Exception as e:
        result_q.put(f"err:{type(e).__name__}")


def test_concurrent_append_same_hash_rejected(tmp_path, anchor, root_kp, signer_kp):
    """S1: N processes each append the SAME signed entry at the same moment.
    Exactly one succeeds; the rest raise DuplicateConfigHash."""
    import multiprocessing as mp
    from dossier_pipeline.registry.trust import save_anchor

    reg_path = tmp_path / "registry.jsonl"
    anchor_path = tmp_path / "anchor.json"
    pubkeys_path = tmp_path / "roots.txt"

    save_anchor(anchor, path=anchor_path)
    pubkeys_path.write_text(
        f"anchorum-root:{root_kp.public_key.public_bytes_raw().hex()}\n"
    )

    snap = {"engine_version": "ccsp-3.3.0", "payload": "x" * 8192}
    entry = sign_entry(
        config_hash=snapshot_hash(snap),
        vertical_id="legal",
        engine_version="ccsp-3.3.0",
        config_snapshot=snap,
        private_key=signer_kp.private_key,
        signer_id=signer_kp.signer_id,
    )

    ctx = mp.get_context("spawn")
    n = 8
    barrier = ctx.Barrier(n)
    q = ctx.Queue()

    procs = [
        ctx.Process(
            target=_concurrent_duplicate_worker,
            args=(entry, str(anchor_path), str(pubkeys_path),
                  str(reg_path), barrier, q),
        )
        for _ in range(n)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)

    results = [q.get() for _ in range(n)]
    ok_count = sum(1 for r in results if r == "ok")

    lines = reg_path.read_text().splitlines()
    parsed = [json.loads(l) for l in lines]

    assert len(lines) == 1, (
        f"expected exactly 1 line, got {len(lines)}; results: {results}"
    )
    assert ok_count == 1, (
        f"expected exactly 1 'ok', got {ok_count}; results: {results}"
    )
    assert parsed[0]["config_hash"] == entry.config_hash
