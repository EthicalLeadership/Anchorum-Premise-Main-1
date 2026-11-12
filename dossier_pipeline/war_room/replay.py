"""Rebuild the war-room stores from a case audit chain.

The stores in this package are in-memory and single-writer by design; the
durable record is the case audit chain. This module is the inverse of the write
path: it projects those rows back into live stores, so a restart does not lose
the case.

Contract:
  - **The payload is the record.** Every entity field a reader needs is in the
    entry, and the builders reconstruct from the entry alone. A row that
    carried only an id would let a restart drop every statement and every
    citation while the chain still claimed the work had happened.
  - **The chain is folded, not replayed step by step.** Status changes and
    supersessions are applied to the created rows and the result is installed
    once. Re-running `update_status`/`supersede` would append new audit rows
    for events that already have one.
  - **Restored rows keep their original `audit_entry_id`.** That id names the
    creation event, and replay must not mint a second one.
  - **Unknown actions are skipped and reported.** A chain written by a newer
    build may contain actions this build has never heard of; crashing is wrong,
    and skipping silently is also wrong — `replay_all().skipped_actions` is how
    a caller tells "nothing was skipped" from "I did not look".
  - **A known action with a missing field raises.** That is a damaged row, not
    forward compatibility, and inventing a value would produce a case that
    never happened.

Deferred:
  - Replay does not re-validate provenance: it cannot, because the stores are
    being built one layer at a time from the same chain. A chain that was
    written by a buggy build replays faithfully, bug included. The hash chain
    is the integrity check; this module is only the projection.
  - Actions are matched by name. A renamed action reads as unknown and is
    skipped, which is the correct behaviour for a *newer* build and a data loss
    for a rename that forgot this list. Keep `replay_builders` in step when
    renaming.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from dossier_pipeline.war_room import replay_builders as builders
from dossier_pipeline.war_room.entities import FrameStore, HypothesisStatus
from dossier_pipeline.war_room.link_register import LinkRegister
from dossier_pipeline.war_room.models import EvidenceResolver, FactBase, FindingStatus
from dossier_pipeline.war_room.uncertainty import UncertaintyRegister


@dataclass(frozen=True)
class ReplayResult:
    """Every store rebuilt from one chain, plus what could not be rebuilt."""

    factbase: FactBase
    frame_store: FrameStore
    uncertainty: UncertaintyRegister
    links: LinkRegister
    #: Action names this build did not recognise, in chain order.
    skipped_actions: list[str] = field(default_factory=list)


# -- fact base -----------------------------------------------------------


def replay_fact_base(
    entries: Iterable[dict[str, Any]], resolver: EvidenceResolver
) -> FactBase:
    """Rebuild a `FactBase` from finding rows. Resolver checks are not re-run."""
    rows = list(entries)
    creations = _creations(rows, builders.ACTION_FINDING_CREATED, "finding_id")
    statuses = _last_value(
        rows, builders.ACTION_FINDING_STATUS_CHANGED, "finding_id", "to"
    )
    supersessions = _supersessions(rows, builders.ACTION_FINDING_SUPERSEDED)

    findings = []
    for finding_id, payload in creations.items():
        raw_status = statuses.get(finding_id)
        findings.append(
            builders.build_finding(
                payload,
                status=FindingStatus(raw_status) if raw_status else None,
                superseded_by=supersessions.get(finding_id),
            )
        )

    factbase = FactBase(resolver)
    factbase.restore(findings)
    return factbase


# -- theory layer --------------------------------------------------------


def replay_frame_store(
    entries: Iterable[dict[str, Any]], factbase: FactBase
) -> FrameStore:
    """Rebuild a `FrameStore` over an already-replayed fact base."""
    rows = list(entries)
    creations = _creations(rows, builders.ACTION_HYPOTHESIS_CREATED, "hypothesis_id")
    statuses = _last_value(
        rows, builders.ACTION_HYPOTHESIS_STATUS_CHANGED, "hypothesis_id", "to"
    )
    supersessions = _supersessions(rows, builders.ACTION_HYPOTHESIS_SUPERSEDED)

    hypotheses = []
    for hypothesis_id, payload in creations.items():
        raw_status = statuses.get(hypothesis_id)
        hypotheses.append(
            builders.build_hypothesis(
                payload,
                status=HypothesisStatus(raw_status) if raw_status else None,
                superseded_by=supersessions.get(hypothesis_id),
            )
        )

    store = FrameStore(factbase)
    store.restore(
        hypotheses=hypotheses,
        assumptions=[
            builders.build_assumption(row)
            for row in _rows(rows, builders.ACTION_ASSUMPTION_CREATED)
        ],
        options=[
            builders.build_option(row)
            for row in _rows(rows, builders.ACTION_OPTION_CREATED)
        ],
        theories=[
            builders.build_theory(row)
            for row in _rows(rows, builders.ACTION_THEORY_CREATED)
        ],
        frames=[
            builders.build_frame(row) for row in _rows(rows, builders.ACTION_FRAME_CREATED)
        ],
    )
    return store


# -- uncertainty and links -----------------------------------------------


def replay_uncertainty(
    entries: Iterable[dict[str, Any]],
    factbase: FactBase,
    frame_store: FrameStore,
) -> UncertaintyRegister:
    """Rebuild an `UncertaintyRegister` over replayed stores."""
    register = UncertaintyRegister(factbase, frame_store)
    register.restore(
        builders.build_gap(row)
        for row in _rows(entries, builders.ACTION_GAP_RECORDED)
    )
    return register


def replay_links(
    entries: Iterable[dict[str, Any]], factbase: FactBase
) -> LinkRegister:
    """Rebuild a `LinkRegister` over an already-replayed fact base."""
    register = LinkRegister(factbase)
    register.restore(
        builders.build_link(row)
        for row in _rows(entries, builders.ACTION_LINK_CREATED)
    )
    return register


# -- everything ----------------------------------------------------------


def replay_all(
    entries: Iterable[dict[str, Any]], resolver: EvidenceResolver
) -> ReplayResult:
    """Rebuild every store from one chain, reporting actions it did not know."""
    rows = list(entries)
    factbase = replay_fact_base(rows, resolver)
    frame_store = replay_frame_store(rows, factbase)
    return ReplayResult(
        factbase=factbase,
        frame_store=frame_store,
        uncertainty=replay_uncertainty(rows, factbase, frame_store),
        links=replay_links(rows, factbase),
        skipped_actions=[
            builders.action_of(row)
            for row in rows
            if builders.action_of(row) not in builders.KNOWN_ACTIONS
        ],
    )


# -- internals -----------------------------------------------------------


def _rows(
    entries: Iterable[dict[str, Any]], action: str
) -> list[dict[str, Any]]:
    return [row for row in entries if builders.action_of(row) == action]


def _creations(
    entries: Iterable[dict[str, Any]], action: str, id_key: str
) -> dict[str, dict[str, Any]]:
    """Creation rows by entity id, in chain order.

    A repeated id keeps its first position and its last payload, matching the
    store's own behaviour: a second create for a live id is refused, so the
    only way to see two is a chain written by a build that did not refuse.
    """
    creations: dict[str, dict[str, Any]] = {}
    for row in entries:
        if builders.action_of(row) == action:
            creations[row[id_key]] = row
    return creations


def _last_value(
    entries: Iterable[dict[str, Any]], action: str, id_key: str, value_key: str
) -> dict[str, Any]:
    """Folded transition state: the last transition per entity wins."""
    folded: dict[str, Any] = {}
    for row in entries:
        if builders.action_of(row) == action:
            folded[row[id_key]] = row[value_key]
    return folded


def _supersessions(
    entries: Iterable[dict[str, Any]], action: str
) -> dict[str, str]:
    """old_id -> new_id for every supersession row of this action."""
    return {
        row["old_id"]: row["new_id"]
        for row in entries
        if builders.action_of(row) == action
    }
