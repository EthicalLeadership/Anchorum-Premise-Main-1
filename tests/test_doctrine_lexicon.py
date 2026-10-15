"""Runner for lexicons/legal-doctrine-v1.yaml.

Layer 1 (regex): every positive matches, every negative is silent.
Layer 2 (engine): the two D-1 assertions. The pattern layer cannot test
what the engine does with negatable_default -- only the engine can. These
two tests are what Phase 0.1 claims; without them, D-1 is an assertion,
not a fact.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LEXICON = REPO_ROOT / "lexicons" / "legal-doctrine-v1.yaml"

CONCEPT_IDS = [
    "DOCTRINE_OFFER", "DOCTRINE_ACCEPTANCE", "DOCTRINE_CONSIDERATION",
    "DOCTRINE_CONTRACT_MODIFICATION", "DOCTRINE_PRE_EXISTING_DUTY",
    "DOCTRINE_UNANTICIPATED_CIRCUMSTANCES", "DOCTRINE_BENEFIT_CONFERRED",
    "DOCTRINE_CHARTER_PROVISION", "DOCTRINE_CLAUSE_RESTATEMENT",
    "DOCTRINE_PROCEDURAL_POSTURE", "DOCTRINE_ISSUE_FRAMING",
    "DOCTRINE_HOLDING",
]


@pytest.fixture(scope="module")
def lex():
    assert LEXICON.exists(), f"missing {LEXICON}"
    return yaml.safe_load(LEXICON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def patterns(lex):
    out: dict[str, list] = {}
    for entry in lex["lexicon"]:
        cid = entry["concept"]
        flags = re.IGNORECASE if "IGNORECASE" in str(entry.get("flags", "")) else 0
        out.setdefault(cid, []).append(
            (entry["pattern"], re.compile(entry["pattern"], flags))
        )
    return out


# --- Layer 1: regex --------------------------------------------------------

def test_concepts_and_tests_align(lex):
    concept_ids = {c["id"] for c in lex["concepts"]}
    test_ids = set(lex["tests"].keys())
    assert concept_ids == test_ids, (
        f"concepts-only={concept_ids - test_ids}, tests-only={test_ids - concept_ids}"
    )


def test_every_concept_has_patterns(lex, patterns):
    for c in lex["concepts"]:
        assert c["id"] in patterns, f"{c['id']} has no patterns"


def test_all_forbidden_false(lex):
    for c in lex["concepts"]:
        assert c.get("forbidden") is False, f"{c['id']} forbidden={c.get('forbidden')!r}"


def test_negatable_default_is_false(lex):
    assert lex["runtime"].get("negatable_default") is False


@pytest.mark.parametrize("concept_id", CONCEPT_IDS)
def test_positive_fires(lex, patterns, concept_id):
    failures = [
        s for s in lex["tests"][concept_id]["positive"]
        if not any(p.search(s) for _, p in patterns[concept_id])
    ]
    assert not failures, f"{concept_id} positives with no match:\n" + "\n".join(
        f"  - {s}" for s in failures
    )


@pytest.mark.parametrize("concept_id", CONCEPT_IDS)
def test_negative_silent(lex, patterns, concept_id):
    failures = []
    for s in lex["tests"][concept_id]["negative"]:
        for raw, p in patterns[concept_id]:
            m = p.search(s)
            if m:
                failures.append((s, raw, m.group(0)))
                break
    assert not failures, f"{concept_id} negatives that matched:\n" + "\n".join(
        f"  - {s}\n      pattern: {p}\n      matched: {g!r}" for s, p, g in failures
    )


# --- Layer 2: engine (the D-1 assertions) ----------------------------------

def _projection_text(proj):
    data = proj.model_dump() if hasattr(proj, "model_dump") else dict(proj)
    return repr(data)


def test_engine_loads_doctrine_lexicon():
    engine = pytest.importorskip("interface.engine")
    fn = getattr(engine, "engine_doctrine", None)
    if fn is None:
        pytest.fail("engine_doctrine not bound; D-1 requires the second binding")
    assert fn() is not None


def test_engine_fires_on_descriptive_concept():
    """D-1: the matcher fires on forbidden: false concepts, not just the loader."""
    from interface.engine import project_doctrine
    proj = project_doctrine("Buyer accepted the offer by signing.")
    assert "DOCTRINE_ACCEPTANCE" in _projection_text(proj), (
        "the engine loaded the lexicon but did not fire on it -- D-1 Option A "
        "does not hold; a second binding is required"
    )


def test_negation_is_not_applied_to_descriptive_concepts():
    """The production engine (ccsp.verify.Engine) applies no negation.

    The brief's sentence is 'The Pre-Existing Duty rule does not apply'.
    ccsp.verify does not read the runtime block, so no negation is applied
    to any concept regardless of `forbidden` or `negatable_default`. The
    'does not' therefore does not suppress the match. This is a property
    of the engine, not of any lexicon flag. If the engine gains negation
    logic later, the lexicon must set the appropriate behaviour explicitly
    and this test's expectation must be re-evaluated.
    """
    from interface.engine import project_doctrine
    proj = project_doctrine("The Pre-Existing Duty rule does not apply here.")
    assert "DOCTRINE_PRE_EXISTING_DUTY" in _projection_text(proj), (
        "the engine suppressed the match on 'does not' despite "
        "negatable_default: false -- the narrow reading is overridden"
    )


def test_pre_existing_duty_general_duty_is_not_rule():
    """The concept is the rule, not the phrase. A general pre-existing duty
    (the pre-existing duty to maintain the premises) must not fire."""
    from interface.engine import project_doctrine
    proj = project_doctrine("The pre-existing duty to maintain the premises was assigned.")
    assert "DOCTRINE_PRE_EXISTING_DUTY" not in _projection_text(proj), (
        "concept fired on a general pre-existing duty, not the rule -- "
        "the pattern is too loose"
    )


def test_holding_does_not_fire_on_non_legal_sense():
    """'The meeting was held that afternoon' must not fire DOCTRINE_HOLDING."""
    from interface.engine import project_doctrine
    proj = project_doctrine("The meeting was held that afternoon at the courthouse.")
    assert "DOCTRINE_HOLDING" not in _projection_text(proj), (
        "concept fired on a non-legal sense of 'held that'"
    )



# --- Layer 3: the ratification hash convention -----------------------------


def test_rules_hash_matches_file_with_hash_fields_blanked():
    """The recorded rules_hash covers the file with rules_hash and config_hash
    blanked to empty strings.

    Convention documented in the header of the ratification block. This is
    the standard 'sign with the signature line empty' rule and has no
    fixed-point problem: writing the hash in does not change what is hashed.
    """
    import hashlib
    import re

    s = LEXICON.read_text(encoding="utf-8")
    blanked = re.sub(r'rules_hash:\s*"[0-9a-f]*"', 'rules_hash: ""', s)
    blanked = re.sub(r'config_hash:\s*"[0-9a-f]*"', 'config_hash: ""', blanked)
    computed = hashlib.sha256(blanked.encode("utf-8")).hexdigest()

    m = re.search(r'rules_hash:\s*"([0-9a-f]+)"', s)
    assert m is not None, "rules_hash not present in the lexicon"
    recorded = m.group(1)
    assert recorded == computed, (
        f"rules_hash in the file ({recorded}) does not match the hash of the "
        f"file with the hash fields blanked ({computed})"
    )
