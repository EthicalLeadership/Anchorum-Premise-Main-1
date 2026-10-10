import sys, yaml
from pathlib import Path
from run_legal_v31 import Runner

doc = yaml.safe_load(Path(sys.argv[1]).read_text())
r = Runner(doc)

adv = doc.get("adversarial_tests", []) or []
split = doc.get("splitter_tests", []) or []

print("=== Adversarial ===")
by_reg = {}
totals = {"total_miss": 0, "wrong_concept": 0, "caught": 0}
for case in adv:
    text, target, reg = case["text"], case["concept"], case.get("register", "?")
    survivors = r.survivors(text)
    fired = [c for c, _ in survivors]
    if target in fired:
        outcome = "caught"
    elif fired:
        outcome = "wrong_concept"
    else:
        outcome = "total_miss"
    totals[outcome] += 1
    by_reg.setdefault(reg, {"caught": 0, "wrong_concept": 0, "total_miss": 0, "n": 0})
    by_reg[reg][outcome] += 1
    by_reg[reg]["n"] += 1
    if outcome != "caught":
        tag = "WRONG" if outcome == "wrong_concept" else "MISS "
        print(f"  {tag} [{reg}] {text!r}")
        if fired:
            print(f"        fired: {fired}")

print()
print("=== Splitter ===")
split_pass = 0
for i, case in enumerate(split):
    survivors = r.survivors(case["text"])
    fired = {c for c, _ in survivors}
    bad = []
    for c in case.get("expect_no_fire", []):
        if c in fired: bad.append(f"unexpected {c}")
    for c in case.get("expect_fire", []):
        if c not in fired: bad.append(f"missing {c}")
    ok = not bad
    split_pass += ok
    print(f"  {'PASS' if ok else 'FAIL'}  [{i}] {case.get('description','')}")
    if bad:
        print(f"        text: {case['text']!r}")
        print(f"        fired: {sorted(fired)}")
        for b in bad: print(f"        {b}")

print()
print("=== Summary ===")
n_adv = len(adv)
print(f"Adversarial: {totals['caught']}/{n_adv} caught  |  "
      f"{totals['wrong_concept']} wrong-concept  |  {totals['total_miss']} total miss")
print(f"Splitter:    {split_pass}/{len(split)} passed")
print()
print("=== By register ===")
for reg, s in by_reg.items():
    print(f"  {reg:12s}  caught {s['caught']}/{s['n']}  "
          f"wrong {s['wrong_concept']}  miss {s['total_miss']}")
