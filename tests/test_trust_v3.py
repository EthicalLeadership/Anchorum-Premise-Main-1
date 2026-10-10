"""Trust anchor v3 invariant tests.

Each test names one invariant from the Design D spec and asserts it.
Run against the current trust.py to see which invariants are enforced.
Run against v3.1 (fixed) to see all pass.

Invariants:
  I1  Genesis anchor has rotation_of is None
  I2  anchor_seq increases by exactly 1 per transition
  I3  issued_at is >= predecessor's issued_at
  I4  expires_at strictly after issued_at
  I5  Signer removal rejected
  I6  Signer pubkey change rejected
  I7  Un-revoke rejected
  I8  revoked_at value is immutable once set
  I9  Adding a signer requires threshold
  I10 Root change requires threshold sigs from prior root set
  I11 Revocation requires 1 sig from current root set (and succeeds)
  I12 verify_anchor checks expiry
  I13 verify_anchor requires root_pubkeys
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from dossier_pipeline.registry import keys as _keys
from dossier_pipeline.registry.trust import (
    Signer,
    TrustError,
    build_anchor,
    revoke,
    rotate,
    verify_anchor,
)


# --- helpers ------------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def kd(tmp_path):
    return tmp_path / "keys"


@pytest.fixture
def roots(kd):
    return {n: _keys.generate_keypair(n, root=kd)
            for n in ("root-A", "root-B", "root-C")}


@pytest.fixture
def signers(kd):
    return {n: _keys.generate_keypair(n, root=kd)
            for n in ("signer-1", "signer-2")}


def _pubs(roots):
    return {rid: kp.public_key for rid, kp in roots.items()}


def _signers_dict(signers):
    now = _iso(_now())
    return {sid: Signer(
        pubkey=kp.public_key.public_bytes_raw().hex(),
        authorized_at=now,
        revoked_at=None,
    ) for sid, kp in signers.items()}


def _genesis(roots, signers, threshold=2):
    return build_anchor(
        root_ids=tuple(roots.keys()),
        threshold=threshold,
        signers=_signers_dict(signers),
        root_private_keys={rid: kp.private_key for rid, kp in roots.items()},
        anchor_seq=0,
    )


def _forge(base, *, signers=None, root_ids=None, threshold=None,
           seq=None, rotation_of=None, issued_at=None, expires_at=None,
           signed_by, all_roots):
    """Construct a mutated copy of `base`, signed by the listed roots."""
    unsigned = dataclasses.replace(
        base,
        signatures={},
        signers=signers if signers is not None else base.signers,
        root_ids=root_ids if root_ids is not None else base.root_ids,
        threshold=threshold if threshold is not None else base.threshold,
        anchor_seq=seq if seq is not None else base.anchor_seq + 1,
        rotation_of=(rotation_of if rotation_of is not None
                     else base.canonical_hash()),
        issued_at=issued_at or _iso(_now()),
        expires_at=expires_at or _iso(_now() + timedelta(days=90)),
    )
    payload = unsigned.canonical_payload()
    sigs = {rid: all_roots[rid].private_key.sign(payload).hex()
            for rid in signed_by}
    return dataclasses.replace(unsigned, signatures=sigs)


def _un_revoke(signers_dict, signer_id):
    out = dict(signers_dict)
    s = out[signer_id]
    out[signer_id] = Signer(
        pubkey=s.pubkey, authorized_at=s.authorized_at, revoked_at=None,
    )
    return out


# --- I1: genesis anchor has rotation_of is None -------------------------

def test_genesis_has_rotation_of_none(roots, signers):
    a = _genesis(roots, signers)
    assert a.rotation_of is None
    assert a.anchor_seq == 0
    verify_anchor(a, _pubs(roots))


def test_genesis_with_rotation_of_rejected(roots, signers):
    a = _genesis(roots, signers)
    forged = _forge(a, rotation_of="0" * 64,
                    signed_by=("root-A", "root-B"), all_roots=roots)
    with pytest.raises(TrustError):
        verify_anchor(forged, _pubs(roots), predecessor=None)


# --- I2: anchor_seq increases by exactly 1 per transition ----------------

def test_seq_increment_by_one_required(roots, signers):
    a0 = _genesis(roots, signers)
    a1 = rotate(
        old_anchor=a0,
        new_root_ids=a0.root_ids,
        new_threshold=a0.threshold,
        root_private_keys={rid: roots[rid].private_key for rid in a0.root_ids},
    )
    verify_anchor(a1, _pubs(roots), predecessor=a0)

    forged = _forge(a0, seq=a0.anchor_seq + 5,
                    signed_by=("root-A", "root-B"), all_roots=roots)
    with pytest.raises(TrustError):
        verify_anchor(forged, _pubs(roots), predecessor=a0)


# --- I3: issued_at is monotonic -----------------------------------------

def test_issued_at_must_not_go_backwards(roots, signers):
    a0 = _genesis(roots, signers)
    earlier = _iso(_now() - timedelta(days=1))
    forged = _forge(a0, issued_at=earlier,
                    signed_by=("root-A", "root-B"), all_roots=roots)
    with pytest.raises(TrustError):
        verify_anchor(forged, _pubs(roots), predecessor=a0)


# --- I4: expires_at strictly after issued_at -----------------------------

def test_expires_at_after_issued_at(roots, signers):
    now = _now()
    with pytest.raises(TrustError):
        build_anchor(
            root_ids=tuple(roots.keys()),
            threshold=2,
            signers=_signers_dict(signers),
            root_private_keys={rid: kp.private_key for rid, kp in roots.items()},
            issued_at=_iso(now),
            expires_at=_iso(now),
        )


# --- I5: signer removal rejected ----------------------------------------

def test_single_root_cannot_remove_signer(roots, signers):
    a0 = _genesis(roots, signers)
    reduced = {sid: s for sid, s in a0.signers.items() if sid != "signer-2"}
    forged = _forge(a0, signers=reduced,
                    signed_by=("root-B",), all_roots=roots)
    with pytest.raises(TrustError):
        verify_anchor(forged, _pubs(roots), predecessor=a0)


# --- I6: pubkey change rejected -----------------------------------------

def test_single_root_cannot_change_pubkey(roots, signers):
    a0 = _genesis(roots, signers)
    changed = dict(a0.signers)
    s = changed["signer-1"]
    changed["signer-1"] = Signer(
        pubkey="ff" * 32,
        authorized_at=s.authorized_at,
        revoked_at=s.revoked_at,
    )
    forged = _forge(a0, signers=changed,
                    signed_by=("root-B",), all_roots=roots)
    with pytest.raises(TrustError):
        verify_anchor(forged, _pubs(roots), predecessor=a0)


# --- I7: un-revoke rejected ----------------------------------------------

def test_single_root_cannot_unrevoke(roots, signers):
    a0 = _genesis(roots, signers)
    a1 = revoke(
        old_anchor=a0,
        signer_id="signer-1",
        root_id="root-A",
        root_private_key=roots["root-A"].private_key,
    )
    forged = _forge(a1, signers=_un_revoke(a1.signers, "signer-1"),
                    signed_by=("root-B",), all_roots=roots)
    with pytest.raises(TrustError):
        verify_anchor(forged, _pubs(roots), predecessor=a1)


# --- I8: revoked_at is immutable once set --------------------------------

def test_revoked_at_is_immutable(roots, signers):
    a0 = _genesis(roots, signers)
    a1 = revoke(
        old_anchor=a0,
        signer_id="signer-1",
        root_id="root-A",
        root_private_key=roots["root-A"].private_key,
    )
    changed = dict(a1.signers)
    s = changed["signer-1"]
    changed["signer-1"] = Signer(
        pubkey=s.pubkey,
        authorized_at=s.authorized_at,
        revoked_at="2000-01-01T00:00:00Z",
    )
    forged = _forge(a1, signers=changed,
                    signed_by=("root-B",), all_roots=roots)
    with pytest.raises(TrustError):
        verify_anchor(forged, _pubs(roots), predecessor=a1)


# --- I9: adding a signer requires threshold ------------------------------

def test_single_root_cannot_add_signer(roots, signers, kd):
    a0 = _genesis(roots, signers)
    new_signers = dict(a0.signers)
    new_kp = _keys.generate_keypair("attacker-signer", root=kd)
    new_signers["attacker-signer"] = Signer(
        pubkey=new_kp.public_key.public_bytes_raw().hex(),
        authorized_at=_iso(_now()),
        revoked_at=None,
    )
    forged = _forge(a0, signers=new_signers,
                    signed_by=("root-B",), all_roots=roots)
    with pytest.raises(TrustError):
        verify_anchor(forged, _pubs(roots), predecessor=a0)


# --- I10: root change requires threshold from prior root set -------------

def test_root_change_requires_prior_threshold(roots, signers, kd):
    a0 = _genesis(roots, signers)
    new_root = _keys.generate_keypair("root-D", root=kd)
    forged = _forge(
        a0,
        root_ids=("root-A", "root-B", "root-D"),
        threshold=2,
        signed_by=("root-A",),
        all_roots={**roots, "root-D": new_root},
    )
    with pytest.raises(TrustError):
        verify_anchor(forged, _pubs(roots), predecessor=a0)


# --- I11: single root can revoke -----------------------------------------

def test_single_root_can_revoke(roots, signers):
    a0 = _genesis(roots, signers)
    a1 = revoke(
        old_anchor=a0,
        signer_id="signer-1",
        root_id="root-A",
        root_private_key=roots["root-A"].private_key,
    )
    verify_anchor(a1, _pubs(roots), predecessor=a0)
    assert a1.signers["signer-1"].revoked_at is not None


# --- I12: verify_anchor checks expiry ------------------------------------

def test_expired_anchor_rejected(roots, signers):
    a0 = _genesis(roots, signers)
    signed_iso = _iso(_now() - timedelta(days=2))
    expired_iso = _iso(_now() - timedelta(days=1))
    forged = _forge(
        a0,
        issued_at=signed_iso,
        expires_at=expired_iso,
        signed_by=("root-A", "root-B"),
        all_roots=roots,
    )
    with pytest.raises(TrustError):
        verify_anchor(forged, _pubs(roots), predecessor=None)


# --- I13: verify_anchor requires root_pubkeys ----------------------------

def test_verify_anchor_requires_root_pubkeys(roots, signers):
    a = _genesis(roots, signers)
    with pytest.raises(TypeError):
        verify_anchor(a)   # noqa


# --- I14: migration produces a fresh genesis (Decision 2a) ---------------

def test_migration_produces_genesis(roots, kd):
    from dossier_pipeline.registry.trust import migrate_v2_to_v3
    v2 = {
        "anchor_version": "2",
        "root_ids": ["root-A", "root-B"],
        "threshold": 2,
        "signers": {"signer-1": "aa" * 32, "signer-2": "bb" * 32},
        "issued_at": "2026-01-01T00:00:00Z",
    }
    migrated = migrate_v2_to_v3(
        v2_anchor=v2,
        root_private_keys={rid: kp.private_key
                           for rid, kp in roots.items()
                           if rid in v2["root_ids"]},
    )
    assert migrated.anchor_version == "3"
    assert migrated.rotation_of is None, (
        "migration must not claim a v2 chain it cannot verify"
    )
    assert migrated.anchor_seq == 0
    verify_anchor(migrated, _pubs(roots), predecessor=None)


# --- I15: migrated anchor verifies as a standalone genesis --------------

def test_migrated_anchor_verifies_as_genesis(roots):
    from dossier_pipeline.registry.trust import migrate_v2_to_v3
    v2 = {
        "anchor_version": "2",
        "root_ids": ["root-A", "root-B", "root-C"],
        "threshold": 2,
        "signers": {"signer-1": "aa" * 32},
        "issued_at": "2026-01-01T00:00:00Z",
    }
    migrated = migrate_v2_to_v3(
        v2_anchor=v2,
        root_private_keys={rid: kp.private_key for rid, kp in roots.items()},
    )
    verify_anchor(migrated, _pubs(roots), predecessor=None)
    assert migrated.signer_pubkey("signer-1") is not None


# --- I16: require_valid_anchor must not skip signature checks -----------

def test_require_valid_anchor_rejects_missing_pubkeys(roots, signers):
    from dossier_pipeline.registry.trust import require_valid_anchor
    a = _genesis(roots, signers)
    with pytest.raises((TypeError, TrustError)):
        require_valid_anchor(a)


# --- I17: anchor round-trip through disk preserves identity -------------

def test_anchor_save_load_roundtrip(roots, signers, tmp_path):
    from dossier_pipeline.registry.trust import save_anchor, load_anchor
    a = _genesis(roots, signers)
    p = tmp_path / "anchor.json"
    save_anchor(a, path=p)
    loaded = load_anchor(path=p)
    assert loaded.canonical_hash() == a.canonical_hash()
    assert loaded.anchor_seq == a.anchor_seq
    assert loaded.signatures == a.signatures
    assert loaded.rotation_of == a.rotation_of


# --- File-format tests (moved from test_trust.py, v3 shapes) ------------

def test_root_pubkeys_from_file_uses_colon(tmp_path, roots):
    from dossier_pipeline.registry.trust import root_pubkeys_from_file
    hex_key = roots["root-A"].public_key.public_bytes_raw().hex()
    p = tmp_path / "roots.txt"
    p.write_text(f"# comment line\nroot-A:{hex_key}\n")
    pubs = root_pubkeys_from_file(p)
    assert "root-A" in pubs
    assert pubs["root-A"].public_bytes_raw().hex() == hex_key


def test_root_pubkeys_from_file_rejects_equals(tmp_path, roots):
    from dossier_pipeline.registry.trust import root_pubkeys_from_file
    p = tmp_path / "roots.txt"
    p.write_text(f"root-A={roots['root-A'].public_key.public_bytes_raw().hex()}\n")
    with pytest.raises(TrustError):
        root_pubkeys_from_file(p)


def test_load_anchor_rejects_unknown_version(roots, signers, tmp_path):
    import json as _json
    from dossier_pipeline.registry.trust import save_anchor, load_anchor
    a = _genesis(roots, signers)
    p = tmp_path / "anchor.json"
    save_anchor(a, path=p)
    data = _json.loads(p.read_text())
    data["anchor_version"] = "999"
    p.write_text(_json.dumps(data))
    with pytest.raises(TrustError):
        load_anchor(path=p)
