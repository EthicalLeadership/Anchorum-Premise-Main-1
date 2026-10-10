"""Adapter between the CCSP engine and GovernedDecisionFlow.

GovernedDecisionFlow is duck-typed: it calls ``engine.project(candidates)``
and reads ``.semantic_hash``, ``.classification``, and ``.admissible`` off
the return value. The CCSP engine (in the top-level ``ccsp`` package) already
returns an object with those attributes.

So this adapter is intentionally thin. Its value is *scoping*: it binds a
lexicon, a vertical identity, and a configured engine into a single object
that the flow can consume without further ceremony — and it exposes the
lexicon hash so callers can register it alongside the projection config.

Two entry points:

  * ``SemanticEngineAdapter`` — wraps an already-constructed engine.
    Use this if you want to share one engine across many decisions.

  * ``build_for_vertical`` — convenience: loads a YAML lexicon, constructs
    an engine scoped to a vertical, and returns the adapter. Raises
    ``ImportError`` if the ``ccsp`` package is not importable.

Neither entry point modifies the engine or its candidates. All projection
semantics (canonicalization, negation, evidence, hashing) live in the
engine itself.
"""
from __future__ import annotations

from typing import Iterable, Optional


class SemanticEngineAdapter:
    """Scoped wrapper around a CCSP engine for a single vertical.

    The engine is duck-typed: any object with a ``project(candidates)``
    method works. This class does not import from ``ccsp``.

    Attributes:
        vertical_id: the vertical this adapter is scoped to.
        lexicon_hash: opaque hash of the lexicon the engine is using, if
            the caller supplies one. Empty string otherwise.
    """

    def __init__(
        self,
        *,
        engine,
        vertical_id: str,
        lexicon_hash: str = "",
    ) -> None:
        if not vertical_id or not isinstance(vertical_id, str):
            raise ValueError("vertical_id must be a non-empty string")
        if not hasattr(engine, "project") or not callable(engine.project):
            raise TypeError(
                "engine must expose a callable .project(candidates) method"
            )
        self._engine = engine
        self._vertical_id = vertical_id
        self._lexicon_hash = lexicon_hash

    @property
    def vertical_id(self) -> str:
        return self._vertical_id

    @property
    def lexicon_hash(self) -> str:
        return self._lexicon_hash

    @property
    def config_hash(self) -> str:
        """Effective config hash of the wrapped engine. Derived, never supplied.

        Tries the attribute names the CCSP engine has used across versions.
        Raises ValueError if none is present, rather than returning a value
        that the caller supplied independently of the engine.
        """
        for name in ("config_hash", "config_hash_", "_ch", "_config_hash"):
            ch = getattr(self._engine, name, None)
            if ch:
                return ch
        raise ValueError(
            "engine does not expose a config_hash; adapter cannot derive one"
        )

    @property
    def engine(self):
        """The underlying engine. Read-only exposure for audit code that
        needs the concrete config_hash (e.g. the flow's registry check)."""
        return self._engine

    def project(self, candidates: Iterable):
        """Delegate to the underlying engine unchanged."""
        return self._engine.project(candidates)


def build_for_vertical(
    *,
    lexicon_path,
    vertical_id: str,
    lexicon_loader=None,
    engine_class=None,
    **engine_kwargs,
):
    """Load a lexicon and construct an adapter scoped to ``vertical_id``.

    Args:
        lexicon_path: path to a YAML lexicon file.
        vertical_id: the vertical identity, e.g. "legal".
        lexicon_loader: optional callable ``(path) -> rules``. Defaults to
            ``ccsp.loader.load_lexicon`` if importable, then
            ``ccsp.verify.load_lexicon``.
        engine_class: optional engine class. Defaults to ``ccsp.Engine``,
            then ``ccsp.verify.Engine``.
        **engine_kwargs: forwarded to the engine constructor (e.g.
            ``confidence_floor``, ``calibration_penalty_pct``).

    Raises:
        ImportError: if the ``ccsp`` package is not importable and no
            ``lexicon_loader``/``engine_class`` override is supplied.
    """
    if lexicon_loader is None:
        lexicon_loader = _default_lexicon_loader()
    if engine_class is None:
        engine_class = _default_engine_class()

    rules = lexicon_loader(lexicon_path)
    engine = engine_class(
        rules=rules,
        vertical_scope=frozenset({vertical_id}),
        **engine_kwargs,
    )
    lexicon_hash = getattr(rules, "hash", "") or ""
    return SemanticEngineAdapter(
        engine=engine,
        vertical_id=vertical_id,
        lexicon_hash=lexicon_hash,
    )


def _default_lexicon_loader():
    # Prefer the loader module if it exists; fall back to the verifier.
    try:
        from ccsp.loader import load_lexicon
        return load_lexicon
    except ImportError:
        pass
    try:
        from ccsp.verify import load_lexicon  # type: ignore
        return load_lexicon
    except ImportError:
        pass
    raise ImportError(
        "no default lexicon loader found; pass lexicon_loader= explicitly"
    )


def _default_engine_class():
    try:
        from ccsp import Engine  # type: ignore
        return Engine
    except ImportError:
        pass
    try:
        from ccsp.verify import Engine  # type: ignore
        return Engine
    except ImportError:
        pass
    raise ImportError(
        "no default engine class found; pass engine_class= explicitly"
    )
