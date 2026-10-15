"""Engine wrapper for the interface.

Two lexicons live here:
  * legal-v3.1.yaml       -- the risk register (the original binding)
  * legal-doctrine-v1.yaml -- the descriptive doctrine lexicon (W5)

The risk register answers "may this text be relied on?".
The doctrine lexicon answers "what area of contract law does this discuss?".
They are separate engines over separate rule sets; no concept crosses.

Projections:
  project_text(text)      -> risk-register projection (unchanged behaviour)
  project_doctrine(text)  -> doctrine projection (new in W5)
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path

from ccsp.verify import Engine, SemanticCandidate, load_lexicon

from interface.gric.schemas import ProjectionResponse

REPO_ROOT = Path(__file__).resolve().parents[1]
LEXICON_PATH = REPO_ROOT / "lexicons" / "legal-v3.1.yaml"
DOCTRINE_LEXICON_PATH = REPO_ROOT / "lexicons" / "legal-doctrine-v1.yaml"

# Both lexicons declare concepts with `scope: [legal]`, so both engines
# are constructed with the same vertical_scope. The engines are separated
# by their rule sets, not by their vertical.
VERTICAL = "legal"


class EngineUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def engine():
    if not LEXICON_PATH.exists():
        raise EngineUnavailable(f"lexicon not found: {LEXICON_PATH}")
    rules = load_lexicon(str(LEXICON_PATH))
    return Engine(rules=rules, vertical_scope=frozenset({VERTICAL}))


@lru_cache(maxsize=1)
def engine_doctrine():
    if not DOCTRINE_LEXICON_PATH.exists():
        raise EngineUnavailable(f"lexicon not found: {DOCTRINE_LEXICON_PATH}")
    rules = load_lexicon(str(DOCTRINE_LEXICON_PATH))
    return Engine(rules=rules, vertical_scope=frozenset({VERTICAL}))


def _candidate(block: str) -> SemanticCandidate:
    return SemanticCandidate(
        raw_text=block,
        normalized_text=block,
        confidence=1.0,
        confidence_calibration="stated",
        evidence=(),
        metadata={},
    )


def _project(text: str, eng: Engine) -> ProjectionResponse:
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = [b.strip() for b in norm.split("\n\n") if b.strip()]
    if not blocks:
        raise ValueError("no non-empty blocks in input")
    cands = [_candidate(b) for b in blocks]
    proj = eng.project(cands)
    return ProjectionResponse.from_projection(proj)


def project_text(text: str) -> ProjectionResponse:
    """Risk-register projection. Unchanged from the original binding."""
    return _project(text, engine())


def project_doctrine(text: str) -> ProjectionResponse:
    """Doctrine-lexicon projection (W5). Separate engine, separate rules."""
    return _project(text, engine_doctrine())


def lexicon_summary(lexicon_path: Path = LEXICON_PATH) -> dict:
    """Metadata for a lexicon file. Defaults to the risk register, so the
    existing caller is unchanged; pass a Path for the doctrine lexicon."""
    import hashlib
    import yaml
    data = {
        "path": str(lexicon_path.relative_to(REPO_ROOT)),
        "exists": lexicon_path.exists(),
    }
    if lexicon_path.exists():
        data["sha256"] = hashlib.sha256(lexicon_path.read_bytes()).hexdigest()
        data["size"] = lexicon_path.stat().st_size
        try:
            parsed = yaml.safe_load(lexicon_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                data["version"] = parsed.get("version", "?")
                concepts = parsed.get("concepts", [])
                patterns = parsed.get("lexicon", [])
                data["concepts"] = len(concepts) if isinstance(concepts, list) else 0
                data["patterns"] = len(patterns) if isinstance(patterns, list) else 0
                data["has_runtime_block"] = "runtime" in parsed
                data["top_keys"] = sorted(parsed.keys())
        except Exception as e:
            data["parse_error"] = str(e)
    return data
