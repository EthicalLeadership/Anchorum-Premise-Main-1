"""Gateway lifecycle state machine.

States: DISCOVERED, DRAFT, VALIDATED, EVALUATED, DOMAIN_APPROVED, PROMOTED.

The factory can write at or below DRAFT only. A write to a gateway above
DRAFT requires --force and demotes it back to DRAFT (any prior validation
is invalidated by content change). No factory code path sets a state
above DRAFT.
"""
from __future__ import annotations

STATES = ("DISCOVERED", "DRAFT", "VALIDATED", "EVALUATED", "DOMAIN_APPROVED", "PROMOTED")
RANK = {s: i for i, s in enumerate(STATES)}
FACTORY_MAX_STATE = "DRAFT"


class LifecycleError(Exception):
    pass


def rank(state: str) -> int:
    if state not in RANK:
        raise LifecycleError(f"unknown lifecycle state {state!r}")
    return RANK[state]


def factory_may_write(current: str | None, *, force: bool) -> str:
    """Return the state the gateway will hold after this write.
    Raises LifecycleError if the transition is refused."""
    if current is None:
        return "DRAFT"
    if current not in RANK:
        raise LifecycleError(f"unknown current state {current!r}")
    if rank(current) <= rank(FACTORY_MAX_STATE):
        return "DRAFT"
    if not force:
        raise LifecycleError(
            f"gateway is at {current}; the factory writes at or below "
            f"{FACTORY_MAX_STATE} only. Rewriting a {current} gateway "
            f"invalidates its validation. Pass --force to demote to {FACTORY_MAX_STATE}."
        )
    return "DRAFT"
