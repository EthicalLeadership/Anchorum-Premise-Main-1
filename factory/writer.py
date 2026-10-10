"""Transactional gateway writer.

    plan -> stage -> validate -> swap

Every write to a gateway passes through here. If any step fails the
destination is unchanged. A partial write never lands.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import FACTORY_VERSION
from .generation_log import LogError, append as log_append
from .keys import Certificate, load_keys, KeyError_
from .lifecycle import LifecycleError, factory_may_write
from .provenance import (
    MANIFEST_NAME, Manifest, ManifestError,
    build_manifest, read_manifest, sha256_file, sha256_str,
    write_manifest_atomic,
)


IGNORED_NAMES = frozenset({
    ".DS_Store", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".git",
})


class WriteRefused(Exception):
    pass


@dataclass(frozen=True)
class WritePlan:
    gateway_dir: Path
    lifecycle_from: str | None
    lifecycle_to: str
    will_replace: tuple[str, ...]
    will_add: tuple[str, ...]
    will_delete: tuple[str, ...]
    human_edited: tuple[str, ...]
    untracked: tuple[str, ...]

    @property
    def is_destructive(self) -> bool:
        return bool(self.human_edited or self.will_delete or self.untracked)

    def summary(self) -> str:
        lines = [
            f"gateway:   {self.gateway_dir}",
            f"lifecycle: {self.lifecycle_from or '(none)'} -> {self.lifecycle_to}",
            f"replace:   {len(self.will_replace)} file(s)",
            f"add:       {len(self.will_add)} file(s)",
            f"delete:    {len(self.will_delete)} file(s)",
        ]
        if self.human_edited:
            lines.append("HUMAN-EDITED (would be overwritten):")
            lines += [f"  {p}" for p in self.human_edited]
        if self.untracked:
            lines.append("UNTRACKED (present, not in manifest):")
            lines += [f"  {p}" for p in self.untracked]
        return "\n".join(lines)

    def acknowledgement(self) -> str:
        return sha256_str(self.summary())


# -------------------------------------------------------------------- plan

def plan_write(gateway_dir: Path, new_files: dict[str, str], *, force: bool) -> WritePlan:
    lifecycle_to = factory_may_write(_peek_lifecycle(gateway_dir), force=force)
    existing = _read_manifest_or_none(gateway_dir)
    manifest_files = {f.path: f.sha256 for f in existing.files} if existing else {}

    will_replace, will_add = [], []
    for rel, content in new_files.items():
        p = gateway_dir / rel
        if not p.is_file():
            will_add.append(rel)
            continue
        if manifest_files.get(rel) == sha256_str(content):
            continue
        will_replace.append(rel)

    will_delete = [p for p in manifest_files if p not in new_files]
    human_edited = []
    for rel, expected in manifest_files.items():
        p = gateway_dir / rel
        if not p.is_file():
            continue
        if sha256_file(p) != expected:
            human_edited.append(rel)
    untracked = _list_untracked(gateway_dir, manifest_files)

    return WritePlan(
        gateway_dir=gateway_dir,
        lifecycle_from=_peek_lifecycle(gateway_dir),
        lifecycle_to=lifecycle_to,
        will_replace=tuple(sorted(will_replace)),
        will_add=tuple(sorted(will_add)),
        will_delete=tuple(sorted(will_delete)),
        human_edited=tuple(sorted(human_edited)),
        untracked=tuple(sorted(untracked)),
    )


# ------------------------------------------------------------------ commit

def commit_write(
    gateway_dir: Path,
    new_files: dict[str, str],
    *,
    inputs_sha256: str,
    source,                              # schema.Source
    force: bool,
    acknowledge: str | None,
    factory_home: Path,
    log_path: Path,
) -> Manifest:
    plan = plan_write(gateway_dir, new_files, force=force)

    if plan.is_destructive and not force:
        raise WriteRefused(
            "refused: writing would destroy or ignore existing content.\n"
            + plan.summary()
            + "\n\nPass --force to proceed."
        )
    if plan.is_destructive and force:
        if acknowledge is None:
            raise WriteRefused(
                "refused: --force requires --acknowledge=<sha256 of plan summary>.\n"
                + plan.summary()
                + f"\n\nExpected --acknowledge={plan.acknowledgement()}"
            )
        if acknowledge != plan.acknowledgement():
            raise WriteRefused(
                f"refused: acknowledgement mismatch.\n"
                f"Expected --acknowledge={plan.acknowledgement()}"
            )

    parent = gateway_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{gateway_dir.name}.staging.", dir=str(parent)))
    backup = parent / f"{gateway_dir.name}.backup.{uuid.uuid4().hex[:12]}"

    try:
        _stage(staging, new_files)
        _validate_staging(staging, parent)

        try:
            keys = load_keys(factory_home)
            cert = keys.certificate
            factory_priv = keys.factory_private_hex
        except KeyError_:
            cert = None
            factory_priv = None

        manifest = build_manifest(
            staging,
            files=sorted(new_files.keys()),
            inputs_sha256=inputs_sha256,
            source=source,
            lifecycle=plan.lifecycle_to,
            factory_version=FACTORY_VERSION,
            factory_private_hex=factory_priv,
            certificate=cert,
        )
        write_manifest_atomic(staging, manifest)
        _fsync_dir(staging)

        had_previous = gateway_dir.exists()
        if had_previous:
            os.replace(gateway_dir, backup)
        try:
            os.replace(staging, gateway_dir)
        except OSError:
            if had_previous and backup.exists():
                os.replace(backup, gateway_dir)
            raise
        _fsync_dir(parent)
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)

        log_append(
            log_path,
            generation_id=manifest.generation_id,
            gateway_name=gateway_dir.name,
            factory_version=FACTORY_VERSION,
            lifecycle=manifest.lifecycle,
            inputs_sha256=inputs_sha256,
            manifest_signature=manifest.signature,
        )
        return manifest

    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if backup.exists() and not gateway_dir.exists():
            os.replace(backup, gateway_dir)
        raise


# ------------------------------------------------------------------ staging

def _stage(staging: Path, new_files: dict[str, str]) -> None:
    for rel, content in new_files.items():
        p = staging / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    (staging / "evals" / "golden").mkdir(parents=True, exist_ok=True)


def _validate_staging(staging: Path, parent: Path) -> None:
    """Load the staged gateway using the real loader. If it fails to load,
    the write is aborted and the destination is untouched."""
    try:
        from dossier_pipeline.gateway import GatewayError, load_gateway
    except ImportError:
        return
    try:
        load_gateway(staging.name, base_path=parent)
    except GatewayError as exc:
        raise WriteRefused(
            f"staged gateway failed to load: {exc}\n"
            f"the destination is unchanged"
        ) from exc


# ------------------------------------------------------------------ helpers

def _peek_lifecycle(gateway_dir: Path) -> str | None:
    m = _read_manifest_or_none(gateway_dir)
    return m.lifecycle if m else None


def _read_manifest_or_none(gateway_dir: Path) -> Manifest | None:
    if not gateway_dir.exists():
        return None
    try:
        return read_manifest(gateway_dir)
    except ManifestError as exc:
        raise WriteRefused(str(exc)) from exc


def _list_untracked(gateway_dir: Path, manifest_files: dict[str, str]) -> list[str]:
    if not gateway_dir.exists():
        return []
    tracked = set(manifest_files)
    tracked.add(MANIFEST_NAME)
    out: list[str] = []
    for root, dirs, files in os.walk(gateway_dir):
        dirs[:] = [d for d in dirs if d not in IGNORED_NAMES]
        for name in files:
            if name in IGNORED_NAMES:
                continue
            full = Path(root) / name
            rel = str(full.relative_to(gateway_dir))
            if rel in tracked:
                continue
            out.append(rel)
    return out


def _fsync_dir(p: Path) -> None:
    try:
        fd = os.open(str(p), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
