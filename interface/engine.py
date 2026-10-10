"""Engine wrapper for the interface.

Loads the legal lexicon once, builds the CCSP engine once.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path

from ccsp.verify import Engine, SemanticCandidate, load_lexicon

from interface.gric.schemas import ProjectionResponse

REPO_ROOT = Path(__file__).resolve().parents[1]
LEXICON_PATH = REPO_ROOT / "lexicons" / "legal-v3.1.yaml"
VERTICAL = "legal"


class EngineUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def engine():
    if not LEXICON_PATH.exists():
        raise EngineUnavailable(f"lexicon not found: {LEXICON_PATH}")
    rules = load_lexicon(str(LEXICON_PATH))
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


def project_text(text: str) -> ProjectionResponse:
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = [b.strip() for b in norm.split("\n\n") if b.strip()]
    if not blocks:
        raise ValueError("no non-empty blocks in input")
    cands = [_candidate(b) for b in blocks]
    proj = engine().project(cands)
    return ProjectionResponse.from_projection(proj)


def lexicon_summary() -> dict:
    import hashlib
    import yaml
    data = {
        "path": str(LEXICON_PATH.relative_to(REPO_ROOT)),
        "exists": LEXICON_PATH.exists(),
    }
    if LEXICON_PATH.exists():
        data["sha256"] = hashlib.sha256(LEXICON_PATH.read_bytes()).hexdigest()
        data["size"] = LEXICON_PATH.stat().st_size
        try:
            parsed = yaml.safe_load(LEXICON_PATH.read_text(encoding="utf-8"))
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
