import argparse, sys, yaml
from pathlib import Path
from classifier import Classifier, make_backend

ap = argparse.ArgumentParser()
ap.add_argument("lexicon")
ap.add_argument("--backend", default="stub",
                help="stub | anthropic | openai | ollama | command:<shell>")
ap.add_argument("--prompt", default="classifier_prompt.txt")
ap.add_argument("-v", "--verbose", action="store_true")
args = ap.parse_args()

doc = yaml.safe_load(Path(args.lexicon).read_text())
prompt = Path(args.prompt).read_text()
clf = Classifier(prompt, make_backend(args.backend))

adv = doc.get("adversarial_tests", []) or []
ben = doc.get("benign_tests", []) or []

print(f"Backend: {args.backend}")
print()
print("=== Adversarial (expect YES) ===")
by_reg = {}
caught = 0
for case in adv:
    text, reg = case["text"], case.get("register", "?")
    got = clf.classify(text)
    by_reg.setdefault(reg, [0, 0])
    by_reg[reg][1] += 1
    by_reg[reg][0] += got
    caught += got
    if args.verbose or not got:
        print(f"  {'HIT ' if got else 'MISS'} [{reg}] {text!r}")

print()
print("=== Benign (expect NO) ===")
fp = 0
for case in ben:
    text, reg = case["text"], case.get("register", "benign")
    got = clf.classify(text)
    fp += got
    if args.verbose or got:
        print(f"  {'F/P ' if got else 'OK  '} [{reg}] {text!r}")

print()
n_a, n_b = len(adv), len(ben)
if n_a:
    print(f"Adversarial recall:      {caught}/{n_a}  ({100*caught/n_a:.0f}%)")
if n_b:
    print(f"Benign false positives:  {fp}/{n_b}  ({100*fp/n_b:.0f}%)")
print()
print("=== By register ===")
for reg, (c, t) in by_reg.items():
    print(f"  {reg:12s}  {c}/{t}")
