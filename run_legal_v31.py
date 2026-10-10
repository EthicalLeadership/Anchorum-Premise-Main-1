import re, sys, yaml

TOKEN_RE = re.compile(r"[A-Za-z]+n't|\d+(?:\.\d+)?%?|[A-Za-z]+|[^\w\s]")


def tokenize(text):
    return [(m.group(), m.start()) for m in TOKEN_RE.finditer(text)]


def is_negator_token(token, negator):
    t, n = token.lower(), negator.lower()
    if t == n:
        return True
    if n == "n't" and t.endswith("n't"):
        return True
    if "?" in n or "\\" in n:
        try:
            return bool(re.fullmatch(n, t))
        except re.error:
            return False
    return False


def negation_in_span(match_start, span_start, tokens, negators, window):
    before = [(t, o) for t, o in tokens if span_start <= o < match_start]
    window_tokens = before[-window:] if window > 0 else []
    window_text = " ".join(t for t, _ in window_tokens).lower()
    for n in negators:
        n_l = n.lower()
        if re.fullmatch(r"[\w']+", n_l):
            if any(is_negator_token(t, n_l) for t, _ in window_tokens):
                return True
        else:
            try:
                if re.search(n_l, window_text):
                    return True
            except re.error:
                if n_l in window_text:
                    return True
    return False


class Runner:
    def __init__(self, doc):
        self.doc = doc
        self.concepts = {c["id"]: c for c in doc.get("concepts", [])}
        rt = doc.get("runtime", {}) or {}
        neg = rt.get("negation", {}) or {}
        self.negators = neg.get("negators", []) or []
        self.window = int(neg.get("negator_window", 15))
        self.negatable_default = rt.get("negatable_default", True)
        matching = rt.get("matching", {}) or {}
        self.default_action = matching.get("default_action", "allow")
        splitting = matching.get("span_splitting", {}) or {}
        self.hard_delims = splitting.get("hard", [";", ".", "?", "!", "\u2014", "--", "\n", ","])
        self.soft_delims = splitting.get("soft", [r"\band\b", r"\bbut\b", r"\bor\b"])
        self.compiled = []
        for entry in doc.get("lexicon", []) or []:
            flags = re.IGNORECASE if "IGNORECASE" in (entry.get("flags") or "") else 0
            try:
                self.compiled.append((entry["concept"], re.compile(entry["pattern"], flags)))
            except re.error as e:
                print(f"[compile-error] {entry.get('concept')}: {e}", file=sys.stderr)

    def split_spans(self, text):
        hard_re = "|".join(re.escape(d) for d in self.hard_delims)
        spans = []
        pos = 0
        for m in re.finditer(hard_re, text):
            spans.append((pos, m.start()))
            pos = m.end()
        spans.append((pos, len(text)))
        soft_re = re.compile("|".join(self.soft_delims), re.IGNORECASE)
        final = []
        for s, e in spans:
            seg = text[s:e]
            p = 0
            for m in soft_re.finditer(seg):
                final.append((s + p, s + m.start()))
                p = m.end()
            final.append((s + p, e))
        return final

    def _raw_fires(self, text):
        out = []
        for cid, rx in self.compiled:
            for m in rx.finditer(text):
                out.append((cid, m))
        out.sort(key=lambda x: (x[1].start(), -x[1].end()))
        return out

    def fire(self, text):
        tokens = tokenize(text)
        spans = self.split_spans(text)
        results = []
        for cid, m in self._raw_fires(text):
            concept = self.concepts.get(cid, {})
            forbidden = bool(concept.get("forbidden"))
            negatable = concept.get("negatable", self.negatable_default)
            negated = False
            if forbidden and negatable:
                span_start = next((s for s, e in spans if s <= m.start() < e), 0)
                negated = negation_in_span(m.start(), span_start, tokens, self.negators, self.window)
            results.append((cid, m, forbidden, negated))
        return results

    def survivors(self, text):
        fires = self.fire(text)
        spans = self.split_spans(text)

        def span_of(pos):
            for i, (s, e) in enumerate(spans):
                if s <= pos < e:
                    return i
            return -1

        grouped = {}
        for row in fires:
            grouped.setdefault(span_of(row[1].start()), []).append(row)

        out = []
        for _, items in grouped.items():
            has_allowed = any((not f) and (not n) for _, _, f, n in items)
            for cid, m, forbidden, negated in items:
                if negated:
                    continue
                if forbidden and has_allowed:
                    continue
                out.append((cid, m))
        return out

    def run_tests(self, verbose=False):
        tests = self.doc.get("tests", {}) or {}
        total = passed = 0
        failures = []
        for cid, cases in tests.items():
            for kind in ("positive", "negative"):
                for i, text in enumerate(cases.get(kind, []) or []):
                    total += 1
                    survivors = self.survivors(text)
                    target_fired = any(c == cid for c, _ in survivors)
                    ok = target_fired if kind == "positive" else not target_fired
                    label = f"{cid}/{kind}[{i}]"
                    if ok:
                        passed += 1
                        if verbose:
                            print(f"  PASS  {label}")
                    else:
                        detail = [(c, f"{m.span()}:{m.group()!r}") for c, m in self._raw_fires(text)]
                        failures.append((label, text, detail))
                        print(f"  FAIL  {label}")
                        print(f"        text: {text!r}")
                        if detail:
                            for c, s in detail:
                                print(f"        fired: {c}  {s}")
                        else:
                            print("        fired: (nothing)")
        print()
        print(f"{passed}/{total} passed")
        if failures:
            print(f"{len(failures)} failure(s):")
            for label, text, _ in failures:
                print(f"  - {label}: {text!r}")
            return 1
        return 0


def main():
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument("lexicon")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    doc = yaml.safe_load(Path(args.lexicon).read_text())
    r = Runner(doc)
    print(f"Loaded {len(r.compiled)} patterns across {len(r.concepts)} concepts; "
          f"window={r.window} tokens, {len(r.negators)} negators, "
          f"default_action={r.default_action}")
    print()
    sys.exit(r.run_tests(verbose=args.verbose))


if __name__ == "__main__":
    main()
