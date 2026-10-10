#!/usr/bin/env python3
"""CCSP self-contained verifier. Zero external deps. Run: python3 verify.py"""
import hashlib, json, math, re, sys, unicodedata
from dataclasses import dataclass, field, asdict
from types import MappingProxyType
from typing import Any, Mapping, Optional

ENGINE_VERSION = "ccsp-3.3.0"
MAX_RAW_BYTES = 1_048_576
MAX_NORMALIZED_CHARS = 100_000
MAX_CANDIDATES = 10_000
MAX_METADATA_BYTES = 16_384
_DOC_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

def _cj(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
def _h(b): return hashlib.sha256(b).hexdigest()
def _freeze(o):
    if isinstance(o, Mapping): return MappingProxyType({k: _freeze(v) for k, v in o.items()})
    if isinstance(o, (list, tuple)): return tuple(_freeze(v) for v in o)
    if isinstance(o, (set, frozenset)): return frozenset(_freeze(v) for v in o)
    return o
def _ci(x): return min(100, max(0, int(round(x * 100))))

@dataclass(frozen=True)
class CanonicalConcept:
    concept_id: str; vertical_scope: frozenset; forbidden: bool; description: str

@dataclass(frozen=True)
class LexiconEntry:
    surface_pattern: Any; concept_id: str; negatable: bool = True
    def __hash__(self): return hash((self.surface_pattern.pattern, self.surface_pattern.flags, self.concept_id, self.negatable))
    def __eq__(self, o):
        return (isinstance(o, LexiconEntry)
                and self.surface_pattern.pattern == o.surface_pattern.pattern
                and self.surface_pattern.flags == o.surface_pattern.flags
                and self.concept_id == o.concept_id
                and self.negatable == o.negatable)

@dataclass(frozen=True)
class CanonicalizationRules:
    version: str; concepts: Mapping; lexicon: tuple; hash: str
    @staticmethod
    def build(version, concepts, lexicon):
        cm = MappingProxyType({c.concept_id: c for c in concepts})
        lt = tuple(lexicon)
        payload = {"version": version,
                   "concepts": [{"id": c.concept_id, "scope": sorted(c.vertical_scope),
                                 "forbidden": c.forbidden, "description": c.description}
                                for c in sorted(cm.values(), key=lambda x: x.concept_id)],
                   "lexicon": [{"pattern": e.surface_pattern.pattern,
                                "flags": e.surface_pattern.flags,
                                "concept": e.concept_id, "negatable": e.negatable}
                               for e in lt]}
        return CanonicalizationRules(version, cm, lt, _h(_cj(payload).encode()))

@dataclass(frozen=True)
class EvidenceRef:
    doc_hash: str; page: Optional[int] = None
    span_start: Optional[int] = None; span_end: Optional[int] = None
    def __post_init__(self):
        if not _DOC_HASH_RE.match(self.doc_hash):
            raise ValueError("bad doc_hash")

@dataclass(frozen=True)
class SemanticCandidate:
    raw_text: str; normalized_text: str; confidence: float
    evidence: tuple = ()
    confidence_calibration: str = "unknown"
    metadata: Mapping = field(default_factory=lambda: MappingProxyType({}))
    confidence_int: int = field(init=False, default=0)
    def __post_init__(self):
        if math.isnan(self.confidence) or not (0.0 <= self.confidence <= 1.0):
            raise ValueError("bad confidence")
        object.__setattr__(self, "metadata", _freeze(dict(self.metadata)))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if len(_cj(dict(self.metadata)).encode()) > MAX_METADATA_BYTES:
            raise ValueError("metadata too large")
        object.__setattr__(self, "confidence_int", _ci(self.confidence))

@dataclass(frozen=True)
class MatchedEntry:
    concept_id: str; span_start: int; span_end: int; clause_offset: int

_SORT_KEY = lambda m: (m.concept_id, m.span_start, m.span_end, m.clause_offset)

_NEG = re.compile(r"\b(?:not|no|never|without|cannot|can't|does\s+not|doesn't|"
                  r"did\s+not|didn't|fails?\s+to|failed\s+to|isn't|aren't|"
                  r"wasn't|weren't)\b", re.I)
_CLAUSE = re.compile(r"[.;:!?]|\b(?:but|however|although|whereas)\b", re.I)
_QUOTES = (('"', '"'), ("\u201c", "\u201d"), ("\u00ab", "\u00bb"))

def _norm(t):
    if len(t.encode()) > MAX_RAW_BYTES: raise ValueError("raw too large")
    t = unicodedata.normalize("NFKC", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > MAX_NORMALIZED_CHARS: raise ValueError("norm too large")
    return t

def _clause_offsets(t):
    out, last = [], 0
    for m in _CLAUSE.finditer(t):
        if m.start() > last:
            out.append((last, t[last:m.start()]))
        last = m.end()
    if last < len(t):
        out.append((last, t[last:]))
    return out

def _quotes(t):
    sp = []
    for oq, cq in _QUOTES:
        st = []
        for i, ch in enumerate(t):
            if ch == oq and (not st or t[st[-1]] != oq or oq != cq): st.append(i)
            elif ch == cq and st:
                s = st.pop()
                if s < i: sp.append((s, i + 1))
    sp.sort()
    mg = []
    for s, e in sp:
        if mg and s < mg[-1][1]: mg[-1] = (mg[-1][0], max(mg[-1][1], e))
        else: mg.append((s, e))
    return mg

def _in_span(p, sp): return any(s <= p < e for s, e in sp)
def _negated(c, ms): return bool(_NEG.search(c[:ms]))

def _canon(text, rules, scope, neg_aware, quote_aware):
    matches, forb = {}, set()
    q = _quotes(text) if quote_aware else []
    for cs, cl in _clause_offsets(text):
        for e in rules.lexicon:
            c = rules.concepts.get(e.concept_id)
            if c is None or not (c.vertical_scope & scope): continue
            for m in e.surface_pattern.finditer(cl):
                ap = cs + m.start()
                if quote_aware and _in_span(ap, q): continue
                if neg_aware and e.negatable and _negated(cl, m.start()): continue
                matches.setdefault(e.concept_id, []).append(
                    MatchedEntry(e.concept_id, ap, ap + len(m.group(0)), cs))
                if c.forbidden: forb.add(e.concept_id)
    return matches, forb

def _eff(c, pen):
    return c.confidence_int if c.confidence_calibration == "calibrated" \
        else (c.confidence_int * pen) // 100
def _rk(c, pen):
    he = 1 if c.evidence else 0
    eh = c.evidence[0].doc_hash if c.evidence else ""
    return (-he, -_eff(c, pen), eh, c.normalized_text)
def _cs(cands, pen, mult):
    return sum(_eff(c, pen) * (mult if c.evidence else 1) for c in cands)

_FB = {
    "no_candidates": "No candidate content was supplied for review.",
    "winning_concept_forbidden": "Dominant canonical concept is forbidden; human review required.",
    "all_below_floor": "All candidates were below the confidence floor; human review required.",
    "all_unmapped": "No candidate mapped to a known canonical concept; human review required.",
    "all_rejected_bounds": "All candidates exceeded size or count bounds; human review required.",
    "mixed": "Candidate set contained no admissible canonical content; human review required.",
    "too_many_candidates": "Candidate count exceeded the limit; human review required.",
    "winner_lacks_evidence": "Winning concept lacked evidence; human review required.",
    "winner_below_floor": "Winning concept was below the confidence floor; human review required.",
}
_FB_DEF = "No admissible canonical projection; human review required."

def _fb_text(r): return _FB.get(r, _FB_DEF)

def _ph(cid, txt, ev, eng, ch, rh, cls, fb, counts, dist, me):
    payload = {"v": 6, "concept_id": cid, "text": txt,
               "evidence": [asdict(e) for e in ev],
               "engine": eng, "config": ch, "rules": rh,
               "classification": cls, "fallback_reason": fb,
               "counts": dict(counts),
               "concept_distribution": dict(sorted(dist.items())),
               "matched_entries": sorted((asdict(m) for m in me),
                                          key=lambda d: (d["concept_id"], d["span_start"],
                                                         d["span_end"], d["clause_offset"]))}
    return _h(_cj(payload).encode())

@dataclass(frozen=True)
class _Proj:
    concept_id: Optional[str]; canonical_text: str; semantic_hash: str
    classification: str; admissible: bool; confidence_int: int
    confidence_calibration: str; evidence: tuple; alternates: tuple
    concept_distribution: Mapping; matched_entries: tuple
    candidate_count: int; admissible_count: int; forbidden_concept_count: int
    below_confidence_count: int; unmapped_count: int; rejected_count: int
    fallback_reason: Optional[str]; engine_version: str; config_hash: str
    rules_hash: str; vertical_scope: frozenset

class Engine:
    def __init__(self, *, rules, vertical_scope, negation_aware=True, quote_aware=True,
                 confidence_floor=0.0, calibration_penalty_pct=70,
                 evidence_weight_multiplier=2, strict_raises=False):
        self.rules = rules; self.scope = frozenset(vertical_scope)
        self.na = negation_aware; self.qa = quote_aware
        self.floor = _ci(confidence_floor); self.pen = calibration_penalty_pct
        self.mult = evidence_weight_multiplier; self.sr = strict_raises
        self._ch = self._config_hash()
    def _config_hash(self):
        return _h(_cj({"engine": ENGINE_VERSION, "hash_algo": "sha256",
                       "rounding_algo": "bankers", "rules_hash": self.rules.hash,
                       "vertical_scope": sorted(self.scope),
                       "negation_pattern": _NEG.pattern, "negation_flags": _NEG.flags,
                       "negation_aware": self.na, "clause_split": _CLAUSE.pattern,
                       "clause_split_flags": _CLAUSE.flags, "quote_pairs": list(_QUOTES),
                       "quote_aware": self.qa, "floor_int": self.floor,
                       "penalty_pct": self.pen, "evidence_weight_multiplier": self.mult,
                       "max_candidates": MAX_CANDIDATES}).encode())
    def project(self, cands):
        cands = list(cands)
        cc = len(cands)
        if cc > MAX_CANDIDATES:
            return self._rej("too_many_candidates", cc)
        bf = rj = um = 0
        buckets, forb, dist, all_m, adm_idx = {}, set(), {}, [], set()
        for idx, c in enumerate(cands):
            try: n = _norm(c.normalized_text)
            except ValueError: rj += 1; continue
            if not n: rj += 1; continue
            if c.confidence_int < self.floor: bf += 1; continue
            m, f = _canon(n, self.rules, self.scope, self.na, self.qa)
            if not m: um += 1; continue
            for cid, ml in m.items():
                dist[cid] = dist.get(cid, 0) + 1
                all_m.extend(ml)
                buckets.setdefault(cid, []).append(SemanticCandidate(
                    raw_text=c.raw_text, normalized_text=n, confidence=c.confidence,
                    evidence=c.evidence, confidence_calibration=c.confidence_calibration,
                    metadata=c.metadata))
                if cid not in f: adm_idx.add(idx)
            forb.update(f)
        counts = {"candidate_count": cc, "admissible_count": len(adm_idx),
                  "forbidden_concepts_matched": len(forb), "below_floor": bf,
                  "unmapped": um, "rejected": rj}
        if not buckets:
            reason = self._empty(cc, bf, um, rj)
            return self._fb(reason, counts, dist, all_m)
        wc = sorted(buckets, key=lambda cid: (-_cs(buckets[cid], self.pen, self.mult),
                                              -len(buckets[cid]), cid))[0]
        if wc in forb:
            return self._fb("winning_concept_forbidden", counts, dist, all_m)
        ranked = sorted(buckets[wc], key=lambda x: _rk(x, self.pen))
        w = ranked[0]
        he = bool(w.evidence); adm = he and w.confidence_int >= self.floor
        if adm: cls = "canonical_projection"; fb = None
        else: cls = "canonical_projection_insufficient"
        if not adm: fb = "winner_lacks_evidence" if not he else "winner_below_floor"
        sh = _ph(wc, w.normalized_text, w.evidence, ENGINE_VERSION, self._ch,
                 self.rules.hash, cls, fb, counts, dist,
                 [m for m in all_m if m.concept_id == wc])
        return _Proj(wc, w.normalized_text, sh, cls, adm, w.confidence_int,
                     w.confidence_calibration, w.evidence, tuple(ranked[1:]),
                     MappingProxyType(dict(dist)),
                     tuple(sorted(all_m, key=_SORT_KEY)),
                     cc, len(adm_idx), len(forb), bf, um, rj, fb,
                     ENGINE_VERSION, self._ch, self.rules.hash, self.scope)
    def _empty(self, tot, bf, um, rj):
        if tot == 0: return "no_candidates"
        cl = []
        if rj: cl.append("rejected_bounds")
        if bf: cl.append("below_floor")
        if um: cl.append("unmapped")
        if len(cl) == 1 and (rj + bf + um) == tot: return "all_" + cl[0]
        return "mixed"
    def _fb(self, r, counts, dist, me):
        t = _norm(_fb_text(r))
        h = _ph(None, t, (), ENGINE_VERSION, self._ch, self.rules.hash,
                "canonical_projection_fallback", r, counts, dist, me)
        return _Proj(None, t, h, "canonical_projection_fallback", False, 0, "unknown",
                     (), (), MappingProxyType(dict(dist)),
                     tuple(sorted(me, key=_SORT_KEY)),
                     counts["candidate_count"], counts["admissible_count"],
                     counts["forbidden_concepts_matched"], counts["below_floor"],
                     counts["unmapped"], counts["rejected"], r,
                     ENGINE_VERSION, self._ch, self.rules.hash, self.scope)
    def _rej(self, r, cc):
        counts = {"candidate_count": cc, "admissible_count": 0,
                  "forbidden_concepts_matched": 0, "below_floor": 0,
                  "unmapped": 0, "rejected": cc}
        t = _norm(_fb_text(r))
        h = _ph(None, t, (), ENGINE_VERSION, self._ch, self.rules.hash,
                "canonical_projection_rejected", r, counts, {}, [])
        return _Proj(None, t, h, "canonical_projection_rejected", False, 0, "unknown",
                     (), (), MappingProxyType({}), (), cc, 0, 0, 0, 0, cc, r,
                     ENGINE_VERSION, self._ch, self.rules.hash, self.scope)

EV = lambda h: (EvidenceRef(doc_hash=h * 64),)

def load_lexicon(path):
    """Load a YAML lexicon into CanonicalizationRules.

    Expected shape:
        version: <str>
        concepts:
          - id: <CONCEPT_ID>
            scope: [<vertical>, ...]
            forbidden: <bool>
            description: <str>
        lexicon:
          - pattern: <regex>
            flags: <str | [str, ...]>   # IGNORECASE | MULTILINE | DOTALL | VERBOSE
            concept: <CONCEPT_ID>
            negatable: <bool>           # optional, default True
    """
    import yaml
    from pathlib import Path as _Path

    _FLAG_MAP = {
        "IGNORECASE": re.IGNORECASE,
        "MULTILINE": re.MULTILINE,
        "DOTALL": re.DOTALL,
        "VERBOSE": re.VERBOSE,
    }

    def _flags(names):
        if names is None:
            return 0
        if isinstance(names, str):
            names = [names]
        f = 0
        for n in names:
            if n not in _FLAG_MAP:
                raise ValueError(
                    f"unknown regex flag {n!r}; allowed: {sorted(_FLAG_MAP)}"
                )
            f |= _FLAG_MAP[n]
        return f

    data = yaml.safe_load(_Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "concepts" not in data or "lexicon" not in data:
        raise ValueError("lexicon must have top-level 'concepts' and 'lexicon'")

    concepts = [
        CanonicalConcept(
            concept_id=c["id"],
            vertical_scope=frozenset(c["scope"]),
            forbidden=bool(c["forbidden"]),
            description=c.get("description", ""),
        )
        for c in data["concepts"]
    ]
    lexicon = [
        LexiconEntry(
            surface_pattern=re.compile(e["pattern"], _flags(e.get("flags"))),
            concept_id=e["concept"],
            negatable=bool(e.get("negatable", True)),
        )
        for e in data["lexicon"]
    ]
    return CanonicalizationRules.build(
        version=data["version"], concepts=concepts, lexicon=lexicon,
    )


def _rules():
    return CanonicalizationRules.build("legal-v1",
        [CanonicalConcept("LEGAL_ESTABLISH_LIABILITY", frozenset({"legal"}), True, ""),
         CanonicalConcept("LEGAL_EVIDENCE_INSUFFICIENT", frozenset({"legal"}), False, "")],
        [LexiconEntry(re.compile(r"establishes liability", re.I), "LEGAL_ESTABLISH_LIABILITY"),
         LexiconEntry(re.compile(r"demonstrates? culpability", re.I), "LEGAL_ESTABLISH_LIABILITY"),
         LexiconEntry(re.compile(r"shows fault", re.I), "LEGAL_ESTABLISH_LIABILITY"),
         LexiconEntry(re.compile(r"insufficient evidence", re.I), "LEGAL_EVIDENCE_INSUFFICIENT")])

def _eng(**kw):
    base = dict(rules=_rules(), vertical_scope=frozenset({"legal"}))
    base.update(kw); return Engine(**base)

def t1():
    r = _eng().project([
        SemanticCandidate("The report establishes liability.",
                          "The report establishes liability.", 0.9, EV("a")),
        SemanticCandidate("Records demonstrate culpability.",
                          "Records demonstrate culpability.", 0.85, EV("b")),
        SemanticCandidate("The incident shows fault.",
                          "The incident shows fault.", 0.8, EV("c")),
        SemanticCandidate("There is insufficient evidence.",
                          "There is insufficient evidence.", 0.9, EV("d"))])
    assert r.concept_id is None, f"concept_id={r.concept_id!r}"
    assert r.classification == "canonical_projection_fallback", f"classification={r.classification!r}"
    assert r.fallback_reason == "winning_concept_forbidden", f"fallback_reason={r.fallback_reason!r}"
    assert r.concept_distribution.get("LEGAL_ESTABLISH_LIABILITY") == 3, f"dist={dict(r.concept_distribution)}"
    return f"concept_id=None reason={r.fallback_reason} dist=L:3 E:1"


def t2():
    import random
    cs = [SemanticCandidate("insufficient evidence one", "insufficient evidence one", 0.9, EV("a")),
          SemanticCandidate("insufficient evidence two", "insufficient evidence two", 0.8, EV("b"))]
    hs = set()
    for s in range(20):
        x = list(cs); random.Random(s).shuffle(x)
        hs.add(_eng().project(x).semantic_hash)
    assert len(hs) == 1
    return f"20 shuffles -> 1 hash ({list(hs)[0][:12]}...)"

def t3():
    rules = CanonicalizationRules.build("legal-v1",
        [CanonicalConcept("LEGAL_EVIDENCE_INSUFFICIENT", frozenset({"legal"}), False, ""),
         CanonicalConcept("LEGAL_PENDING_REVIEW", frozenset({"legal"}), False, "")],
        [LexiconEntry(re.compile(r"insufficient evidence", re.I), "LEGAL_EVIDENCE_INSUFFICIENT"),
         LexiconEntry(re.compile(r"pending review", re.I), "LEGAL_PENDING_REVIEW")])
    e = Engine(rules=rules, vertical_scope=frozenset({"legal"}))
    r = e.project([SemanticCandidate(f"pending review {i}", f"pending review {i}", 0.10,
                                      (EvidenceRef(doc_hash=f"{i:064x}"),)) for i in range(5)]
                  + [SemanticCandidate("insufficient evidence", "insufficient evidence",
                                       0.99, (EvidenceRef(doc_hash="f" * 64),))])
    assert r.concept_id == "LEGAL_EVIDENCE_INSUFFICIENT"
    return f"{r.concept_id} (plurality -> PENDING_REVIEW)"

def t4():
    assert "all_forbidden" not in _FB
    reach = {_eng().project([]).fallback_reason,
             _eng(confidence_floor=0.5).project(
                 [SemanticCandidate("insufficient evidence", "insufficient evidence", 0.1, EV("a"))]).fallback_reason,
             _eng().project([SemanticCandidate("nothing here", "nothing here", 0.9, EV("a"))]).fallback_reason,
             _eng().project([SemanticCandidate("establishes liability", "establishes liability", 0.9, EV("a"))]).fallback_reason}
    for r in reach: assert r in _FB
    return f"emitted={sorted(reach)} phantom=0"

def t5():
    r = _eng().project([SemanticCandidate("The report does not establish liability.",
                                          "The report does not establish liability.", 0.9, EV("a"))])
    assert r.concept_id is None and r.unmapped_count == 1
    return f"unmapped_count=1 classification={r.classification}"

def t6():
    a, b = _eng()._ch, _eng(calibration_penalty_pct=50)._ch
    assert a != b; return f"{a[:12]}... != {b[:12]}..."

def t7():
    a, b = _eng()._ch, _eng(evidence_weight_multiplier=3)._ch
    assert a != b; return f"{a[:12]}... != {b[:12]}..."

def t8():
    cs = [SemanticCandidate("insufficient evidence", "insufficient evidence", 0.9, EV("a"))]
    a, b = _eng().project(cs).semantic_hash, _eng().project(cs).semantic_hash
    assert a == b; return f"two runs -> {a[:12]}..."

TESTS = [("T1 worked example (Design A)", t1),
         ("T2 permutation invariance", t2),
         ("T3 confidence beats plurality", t3),
         ("T4 no phantom fallback reasons", t4),
         ("T5 negation respected", t5),
         ("T6 config_hash changes with penalty", t6),
         ("T7 config_hash changes with evidence mult", t7),
         ("T8 determinism across runs", t8)]

def main():
    print(f"CCSP {ENGINE_VERSION} - self-contained verifier")
    print("=" * 68)
    p = f = 0
    for name, fn in TESTS:
        try:
            d = fn(); print(f"  PASS  {name}"); print(f"        {d}"); p += 1
        except AssertionError as e:
            print(f"  FAIL  {name}"); print(f"        {e}"); f += 1
        except Exception as e:
            print(f"  ERROR {name}"); print(f"        {type(e).__name__}: {e}"); f += 1
    print("=" * 68)
    print(f"  {p} passed, {f} failed")
    return 0 if f == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
