"""
Dossier DOSSIER-PIPELINE Declarative state machine loader, validator, and strict runtime.

This module treats the JSON spec as the source of truth and provides a runtime
enforcement layer that rejects illegal state mutation at transition boundaries.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Set


class StateMachineSpecError(ValueError):
    """Raised when the state machine spec is malformed."""


class SpecViolation(RuntimeError):
    """Raised when runtime execution diverges from the declarative spec."""


@dataclass(frozen=True)
class TransitionEvent:
    from_state: str
    event: str
    to_state: str
    payload_hash: str
    sequence_no: int


@dataclass
class TransitionTrace:
    events: List[TransitionEvent] = field(default_factory=list)

    def record(self, from_state: str, event: str, to_state: str, payload: Mapping[str, Any] | None = None) -> TransitionEvent:
        payload_hash = hashlib.sha256(
            json.dumps(payload or {}, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()
        transition = TransitionEvent(
            from_state=from_state,
            event=event,
            to_state=to_state,
            payload_hash=payload_hash,
            sequence_no=len(self.events) + 1,
        )
        self.events.append(transition)
        return transition

    def hash(self) -> str:
        encoded = json.dumps([asdict(event) for event in self.events], sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class StateMachineSpec:
    version: int
    states: Dict[str, Dict[str, str]]
    terminal_states: Set[str]

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> "StateMachineSpec":
        version = raw.get("version")
        if not isinstance(version, int):
            raise StateMachineSpecError("Spec field 'version' must be an integer")

        states_raw = raw.get("states")
        if not isinstance(states_raw, Mapping) or not states_raw:
            raise StateMachineSpecError("Spec field 'states' must be a non-empty mapping")

        terminal_raw = raw.get("terminal_states")
        if not isinstance(terminal_raw, list):
            raise StateMachineSpecError("Spec field 'terminal_states' must be a list")

        states: Dict[str, Dict[str, str]] = {}
        for state_name, transitions_raw in states_raw.items():
            if not isinstance(state_name, str) or not state_name:
                raise StateMachineSpecError("State names must be non-empty strings")
            if not isinstance(transitions_raw, Mapping):
                raise StateMachineSpecError(f"Transitions for '{state_name}' must be a mapping")

            transitions: Dict[str, str] = {}
            for event_name, next_state in transitions_raw.items():
                if not isinstance(event_name, str) or not event_name:
                    raise StateMachineSpecError(f"Event names for '{state_name}' must be non-empty strings")
                if not isinstance(next_state, str) or not next_state:
                    raise StateMachineSpecError(
                        f"Transition target for '{state_name}.{event_name}' must be a non-empty string"
                    )
                transitions[event_name] = next_state
            states[state_name] = transitions

        terminal_states = set()
        for state_name in terminal_raw:
            if not isinstance(state_name, str) or not state_name:
                raise StateMachineSpecError("Terminal states must be non-empty strings")
            terminal_states.add(state_name)

        spec = cls(version=version, states=states, terminal_states=terminal_states)
        spec.validate()
        return spec

    @classmethod
    def load(cls, path: str | Path) -> "StateMachineSpec":
        spec_path = Path(path)
        raw = json.loads(spec_path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise StateMachineSpecError("Spec root must be a mapping")
        return cls.from_dict(raw)

    def validate(self) -> None:
        defined_states = set(self.states.keys())
        referenced_states = set()

        if "RECEIVED" not in defined_states:
            raise StateMachineSpecError("Spec must define a 'RECEIVED' state")

        for state_name, transitions in self.states.items():
            for event_name, next_state in transitions.items():
                referenced_states.add(next_state)
                if next_state not in defined_states and next_state not in self.terminal_states:
                    raise StateMachineSpecError(
                        f"Transition '{state_name}.{event_name}' targets unknown state '{next_state}'"
                    )

        for terminal_state in self.terminal_states:
            if terminal_state in self.states and self.states[terminal_state]:
                raise StateMachineSpecError(
                    f"Terminal state '{terminal_state}' must not define outgoing transitions"
                )

        unresolved = referenced_states - defined_states - self.terminal_states
        if unresolved:
            raise StateMachineSpecError(f"Spec references unresolved states: {sorted(unresolved)}")

    def validate_transition(self, state: str, event: str) -> str:
        allowed = self.states.get(state, {})
        if event not in allowed:
            raise StateMachineSpecError(f"Invalid transition: state='{state}' event='{event}'")
        return allowed[event]


class StrictStateMachine:
    def __init__(self, spec: StateMachineSpec, initial_state: str = "RECEIVED"):
        if initial_state not in spec.states:
            raise StateMachineSpecError(f"Initial state '{initial_state}' is not defined in the spec")
        self.spec = spec
        self.state = initial_state
        self.trace = TransitionTrace()

    def apply(self, event: str, payload: Mapping[str, Any] | None = None) -> str:
        expected_next = self.spec.validate_transition(self.state, event)
        previous_state = self.state
        self.trace.record(previous_state, event, expected_next, payload)
        self.state = expected_next
        if self.state != expected_next:
            raise SpecViolation(
                f"Spec drift detected: {previous_state} + {event} expected {expected_next}, got {self.state}"
            )
        return self.state

    def current_state(self) -> str:
        return self.state


DEFAULT_SPEC_PATH = Path(__file__).with_name("state_machine_spec.json")


def load_default_spec() -> StateMachineSpec:
    return StateMachineSpec.load(DEFAULT_SPEC_PATH)
