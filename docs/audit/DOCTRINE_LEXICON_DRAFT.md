# Doctrine lexicon draft for review ANCH-2026-10-12-01 W5

**Status: DRAFT. Not wired in. No code or lexicon file has been changed by this
document.** It is the concept list `docs/audit/CONNECTOR_REMEDIATION_PLAN.md` §9.3
step 5.1 makes the blocking input for `W5`, written for the product owner to keep,
cut or edit. `lexicons/legal-doctrine-v1.yaml` does not exist yet and nothing
reads it.

**What it implements.** §13 D-1, Option A: a second lexicon and a second engine.
`lexicons/legal-v3.1.yaml` stays the risk register and does not move. The doctrine
lexicon answers a different question:

| | risk register (`legal-v3.1.yaml`) | doctrine lexicon (this draft) |
|---|---|---|
| question | may this text's assertions be relied on, or does it need human review? | what area of contract law does this text discuss? |
| concepts | `forbidden: true` for assertions of liability, violation, guilt; `forbidden: false` for hedged, negative, procedural, attributive | descriptive only |
| `admissible` | meaningful: it is the register's whole point | not meaningful, and must not be reported as if it were |
| consumers | GRIC projection view, `SemanticEngineAdapter` | the analysis route, alongside the risk projection |

**The positives below are quoted from the brief** (`Angel v. Murray`,
322 A.2d 630 (R.I. 1974), SHA-256 `c58fcf24...`), scope by scope, so the coverage
claim is checkable rather than asserted. The negatives are the load-bearing part:
they are the sentences the concept must **not** fire on.

## How to read the examples

Three kinds of false positive matter here, and each is represented in the negatives
below.

1. **Mention is not application.** A brief names a doctrine in order to say it does
   not apply, or to report that a party raised it. Firing on those turns "the
   pre-existing duty rule does not apply" into a match for
   `DOCTRINE_PRE_EXISTING_DUTY` and tells a reader the opposite of the text.
2. **Reported speech is not the brief's own voice.** "The complaint asserted that
   the payments were illegal" is the brief describing a pleading. The risk
   register already handles this shape with `LEGAL_ATTRIBUTED_FINDING` and its
   `benign_tests` are the precedent followed here.
3. **Vocabulary is not doctrine.** The word "consideration" appears in ordinary
   English ("under consideration", "for consideration of the court"). A pattern
   keyed on the bare noun will match a scheduling sentence.

## Concept list

### `DOCTRINE_OFFER`

**Definition.** The text identifies a proposal by one party as an offer capable of
acceptance, or discusses whether a communication amounted to one.

**Positive examples.**

- "Maher had held a series of 5 year contracts with the City of Newport since 1946"
  (the contracts are identified as concluded agreements; see the acceptance
  concept for the pairing).
- A brief stating "Maher offered to continue the refuse-collection service for a
  further five years" would fire. The brief before us describes the contracts as
  already formed, so this concept is expected to be a **near miss** on this
  document and is included because the owner's list asks for it.

**Negative examples.**

- "The parties disagree about the interpretation of section 12."
- "Counsel offered no authority for the proposition."

**Why the negatives matter.** "Offer" is a high-frequency word in procedural
prose. A pattern that fires on "counsel offered" or "the respondent offered no
evidence" produces a doctrine match out of argumentative vocabulary.

### `DOCTRINE_ACCEPTANCE`

**Definition.** The text identifies assent to an offer, or discusses whether
conduct or silence amounted to acceptance.

**Positive examples.**

- "In March 1964, a new contract for this service was enacted for another 5 years."
- "the city council obliged his requests for extra compensation for two
  consecutive years."

**Negative examples.**

- "The Court of Appeal allowed the appeal." ("allowed" is not contractual assent.)
- "The tribunal accepted the respondent's account of the meeting." (evidential
  acceptance, not contractual)

**Why the negatives matter.** "Accepted" and "allowed" both mean assent in
ordinary usage and neither is a contract formation event. The negative examples pin
the distinction to *contract formation*, not to the verb.

### `DOCTRINE_CONSIDERATION`

**Definition.** The text discusses consideration as an element of contract:
whether it exists, whether it is required, or whether it is sufficient.

**Positive examples.**

- "The issue centered on whether this extra payment was illegal due to lack of
  proper consideration"
- "A contract modification only requires consideration if it is fair and equitable"

**Negative examples.**

- "The Court took the matter under consideration."
- "Whether there is a prima facie case is a matter for the hearing panel."
- "The Commission is currently reviewing the submissions of both parties."

**Why the negatives matter.** This is the sharpest trap in the set. "Under
consideration" and "took the matter under consideration" are ordinary procedural
phrases, and a bare-noun pattern will match every one of them. The pattern must
require a contractual frame (consideration *for*, *lack of*, *required*,
*supported by*, *sufficient*), not the noun alone.

### `DOCTRINE_CONTRACT_MODIFICATION`

**Definition.** The text discusses a change to an existing agreement, including
whether the change needed to be supported by new consideration.

**Positive examples.**

- "A contract modification only requires consideration if it is fair and equitable
  in view of circumstances unanticipated by both parties at the contracts
  inception."
- "Contract modifications are enforceable without new consideration if they address
  unanticipated circumstances that alter initial contractual duties."
- "The Supreme Court decided that unforeseen circumstances justified the contract
  modification without additional consideration"

**Negative examples.**

- "The parties agreed to settle the matter without admission of liability."
  (a settlement in the risk register's `benign_tests`, not a modification)

**Why the negatives matter.** A modification and a settlement are both changes to
the parties' positions. Firing on settlement would report a litigation event as a
contract-law event.

### `DOCTRINE_PRE_EXISTING_DUTY`

**Definition.** The text discusses the rule that performance of an existing duty is
not consideration for a new promise.

**Positive example and negative example, deliberately the same sentence.** The
brief contains one statement of this rule, and it is the whole reason this concept
needs an owner's decision:

- the sentence is `"The Pre-Existing Duty rule does not apply when there are
  reasonable grounds for modifying a contract, even if additional payment is
  involved."`

Whether that sentence counts as a **positive** or a **negative** for this concept
is the open question below, and the draft does not answer it by fiat. Note also
that the risk register's `adversarial_tests` and its `benign_tests` do not transfer
to this lexicon: they exist to police assertions of a finding, and a descriptive
concept has no finding to police.

**Why the negative matters.** The brief's single clearest statement of the rule is
a *negative* application: the rule does **not** apply. A pattern that fires on the
phrase reports a match and, worse, the text right beside it says the opposite. The
owner must decide which reading the concept intends:

- **Narrow:** the concept means "this text raises the pre-existing duty rule",
  firing on the sentence above, and the *result* must never be read as "the rule
  was applied". Under this reading the concept is about topic coverage only.
- **Application-aware:** the concept means "this text applies the rule", and the
  sentence above must **not** fire, needing a `runtime.negation`-style suppression
  like the risk register's.

This draft recommends the **narrow** reading, because a descriptive taxonomy should
answer "does this document discuss X" and leave "did X decide the case" to a reader.
It is flagged as an open question below rather than assumed.

### `DOCTRINE_UNANTICIPATED_CIRCUMSTANCES`

**Definition.** The text discusses circumstances not anticipated by the parties at
formation, or impracticability and frustration as a consequence of them.

**Positive examples.**

- "he faced an unanticipatedupsurge in costs due to a sudden increase of 400 new
  dwelling units"
- "Maher faced considerably higher operational costs because of this unexpected
  jump in new dwellings."
- "circumstances unanticipated by both parties at the contracts inception"
- "unforeseen increases in housing units"

**Negative examples.**

- "The inquiry has not yet concluded."
- "The respondent's explanation does not survive contact with the documentary
  record."

**Why the negatives matter.** "Unexpected" and "unforeseen" describe facts in both
contracts and litigation. The concept must require the circumstance to bear on
performance of an agreement, and the second negative pins that.

### `DOCTRINE_BENEFIT_CONFERRED`

**Definition.** The text discusses a benefit received by one party as the basis for
a promise, in the sense the Restatement uses for a benefit conferred.

**Positive examples.**

- "he requested an additional $10,000 per year to address this unforeseen rise in
  service requirements"

**Negative examples.**

- "Damages of $20,000 were awarded." (a remedy, not a benefit conferred)
- "Any fair reading of the file places the respondent in an unenviable position."

**Why the negatives matter.** The concept is close to damages vocabulary. The
negative pins the direction: money reaching a party *as consideration for a
promise*, not money awarded by a court.

### `DOCTRINE_CHARTER_PROVISION`

**Definition.** The text discusses a limitation on a public body's contracting
power, such as a municipal charter's requirements for amending an agreement.

**Positive examples.**

- "contrary to municipal charter requirements"
- "the city charter restricted the councils power by requiring a written
  recommendation from the city manager before amending contracts"
- "Municipal charters should notbe interpreted to restrict city council powers in
  amending existing contracts"

**Negative examples.**

- "The Commission's reasons will be released at a later date."
- "the interpretation of section 12" (a section of any instrument; the concept
  requires a *public body's contracting power*)

**Why the negatives matter.** "Charter" and "section" appear in regulatory prose
that has nothing to do with a municipality's capacity to amend a contract.

### `DOCTRINE_CLAUSE_RESTATEMENT`

**Definition.** The text cites the Restatement of the Law as authority.

**Positive examples.**

- "The court applied : Restatement Second of the Law of Contracts § 89D(a)"

**Negative examples.**

- "The parties agree with the restatement of the facts in the agreed statement of
  facts." (a restatement of facts is not the Restatement)

**Why the negatives matter.** "Restatement" as a common noun is a routine word in
litigation. The pattern must require the treatise citation form.

### `DOCTRINE_CITATION_REPORTER`

**Definition.** The text carries a reporter citation identifying decided authority.

**Positive examples.**

- "322 A.2d 630 1974 CONTRACTS"
- The brief's running footer combines the citation with the case name, which is why
  the pattern is structural rather than vocabulary-based.

**Negative examples.**

- "§ 89D(a)" (a provision, not a reporter citation)
- "10/10/26, 23:29" (a print timestamp; the brief's own footer shows how close a
  date-like token comes to a citation volume and page)

**Why the negatives matter.** The citation pattern the product already uses for
the `CITATION` scope is structural (`^\s*\d+\s+[A-Za-z][\w.]*\s+\d+\s+\d{4}\s+[A-Z]{2,}\b`).
This concept should reuse that, not a looser one, or every "400 new dwelling units"
becomes a citation.

### `DOCTRINE_PROCEDURAL_POSTURE`

**Definition.** The text describes where the matter stands procedurally: how it
reached this court, what the court below did, or what judgment is under review.

**Positive examples.**

- "A Superior Court justice heard the case without a jury and ruled in favor of the
  plaintiffs, ordering Maher to repay Newport."
- "Maher appealed the decision to the Rhode Island Supreme Court."
- "The Rhode Island Supreme Court reversed the lower courts decision"

**Negative examples.**

- "The applicant seeks judicial review of the decision below." (this sentence is in
  the risk register's `benign_tests`; it is procedural but states no outcome)
- "The tribunal will hear argument on the merits in due course."

**Why the negatives matter.** A procedural sentence that states no posture
outcome should not be a posture match, or every scheduling line in a file becomes
one.

### `DOCTRINE_ISSUE_FRAMING`

**Definition.** The text states the question the court had to decide.

**Positive examples.**

- "Whether the $20,000 paid additionally to Maher under an existing refuse
  collection contract with the City of Newport was unlawfully dispensed without
  proper consideration"
- "The issue centered on whether this extra payment was illegal"
- "The dispute centered on incremental payments made mid-contract"

**Negative examples.**

- "Whether there is a prima facie case is a matter for the hearing panel."
- "Whether the conduct constitutes a violation remains to be determined."
- "The Commission takes no position on whether the conduct was lawful."

**Why the negatives matter.** All three negatives are risk-register `benign_tests`
entries. Each opens with "whether", and none is the court's own framing of the
question it decided. The concept must key on *the question framed for decision*,
which is why the positive examples above are the issue scope and not every
"whether" sentence in the document.

### `DOCTRINE_HOLDING`

**Definition.** The text states the court's disposition, or the rule it settled.

**Positive examples.**

- "The Rhode Island Supreme Court reversed the lower courts decision and held that
  Maher was not required to repay the $20,000 to the city."
- "The Supreme Court decided that unforeseen circumstances justified the contract
  modification without additional consideration, reversing the lowercourts demand
  for reimbursement."

**Negative examples.**

- "The Court of Appeal allowed the appeal and remitted the matter for
  reconsideration." (a disposition reported without a rule; decide whether this is
  in scope for the owner's taxonomy)
- "The regulator's preliminary assessment did not identify any concerns."

**Why the negatives matter.** A holding concept that fires on any disposition
overlaps the procedural-posture concept and reports every remand as a holding. The
positive examples both pair a disposition with the rule decided, which is the
distinction the negatives pin.
## Coverage this concept list is expected to give

Measured on the brief today: 8 scopes, 1 matched, 7 fell back, and the analysis
reports a warning that the lexicon covered 1 of 8. The table below is the expected
effect if this list is approved and authored as described. It is a prediction to be
checked, not a claim: the pattern text does not exist yet.

| brief scope | concept(s) that should match | today |
|-------------|------------------------------|-------|
| `CITATION` | `DOCTRINE_CITATION_REPORTER` | no match |
| `FACTS` | `DOCTRINE_UNANTICIPATED_CIRCUMSTANCES`, `DOCTRINE_BENEFIT_CONFERRED` (and the risk register's `LEGAL_ALLEGATION`, which already matches) | matches on the risk register only |
| `PROCEDURAL_POSTURE` | `DOCTRINE_PROCEDURAL_POSTURE` | no match |
| `ISSUE` | `DOCTRINE_ISSUE_FRAMING`, `DOCTRINE_CONSIDERATION`, `DOCTRINE_CHARTER_PROVISION` | no match |
| `RULE` | `DOCTRINE_CONTRACT_MODIFICATION`, `DOCTRINE_CONSIDERATION` | no match |
| `REASONING` | `DOCTRINE_UNANTICIPATED_CIRCUMSTANCES`, `DOCTRINE_CHARTER_PROVISION`, `DOCTRINE_CLAUSE_RESTATEMENT` | no match |
| `HOLDING` | `DOCTRINE_HOLDING`, `DOCTRINE_PROCEDURAL_POSTURE` | no match |
| `DISTILLED_RULES` | `DOCTRINE_CONTRACT_MODIFICATION`, `DOCTRINE_PRE_EXISTING_DUTY`, `DOCTRINE_CHARTER_PROVISION` | no match |

If that holds, coverage goes from 1 of 8 to 8 of 8 and the warning clears for this
document. Two consequences are worth stating before anyone approves it:

- **The warning clearing is not by itself good news.** The warning exists because a
  document the engine cannot read was being presented as though it had been read.
  If the doctrine patterns are written too loosely, this brief and every other
  document will "match" and the warning will never appear for anything. The
  negative examples are what keeps the warning meaningful, which is why they are
  the load-bearing part of this draft and why the coverage test after approval must
  assert both directions: the brief matches, **and** each negative example above
  still does not.
- **`DOCTRINE_OFFER` is expected to be a near miss.** The brief describes concluded
  agreements, not the formation steps. If it matches anyway, the pattern is too
  loose and that is the first thing to check.

## Open questions for the owner

Each is a decision this draft deliberately does not make.

1. **`DOCTRINE_PRE_EXISTING_DUTY`: narrow or application-aware?** See that concept
   above. The recommendation is narrow (the concept marks topic coverage; "does
   this document discuss X", not "did X decide the case"), because an
   application-aware reading needs negation suppression and starts to duplicate the
   risk register's job.
2. **Is a disposition without a rule a `DOCTRINE_HOLDING`?** "The Court of Appeal
   allowed the appeal and remitted the matter for reconsideration" is a real
   sentence shape and the brief's own holding pairs the two. Choose one, because a
   `DOCTRINE_HOLDING` that fires on every disposition overlaps
   `DOCTRINE_PROCEDURAL_POSTURE` and makes the two concepts indistinguishable.
3. **Should `DOCTRINE_*` concepts ever set `forbidden: true`?** This draft assumes
   no: the register asks a risk question and the doctrine lexicon asks a descriptive
   one. If any doctrine concept is `forbidden: true`, the two registers have been
   merged and Option A's benefit is gone.
4. **What does the API report, and where?** Plan §9.3 step 5.4 says both
   projections are reported, each labelled, each with its own `lexiconHash` and
   `configHash`, and that `W4`'s `coverage` block becomes per-projection. Two
   shapes are possible and this changes the wire contract, so it is the owner's
   call rather than the implementer's:
   - **Shape 1, nested.** `GET /evidence/{id}/analysis` gains
     `"projections": {"risk": {...}, "doctrine": {...}}`, each with its own
     `scopes`, `coverage`, `lexiconHash` and `configHash`, and the existing
     top-level `scopes`/`coverage` are kept as the risk projection for
     compatibility.
   - **Shape 2, additive.** The existing top-level keys stay exactly as they are
     (the risk projection), and a new `"doctrine": {"concepts": [...],
     "coverage": {...}, "lexiconHash": ..., "configHash": ...}` key is added beside
     them, where `doctrine.concepts` is the per-scope list of matched doctrine
     concepts.
   This draft recommends **Shape 2**: it is additive, it does not move the existing
   pins in `tests/test_evidence_analysis_api.py`, and the risk projection stays the
   default reading of `scopes`.
5. **Does the doctrine projection belong in the signed record?** Under Option A the
   doctrine concepts are descriptive, not risk assertions, so there is a real
   question whether they should reach the pipeline's committed record at all or
   stay in the product API's own store. This draft takes no position and notes only
   that if they do reach a pipeline payload, rule 4.2 of the plan applies: an
   unnamed field is exported in the clear.
6. **Vertical id and file name.** The draft assumes `lexicons/legal-doctrine-v1.yaml`
   with its own vertical scope (for example `legal-doctrine`) so the two engines
   cannot be confused. Rename if the taxonomy owner prefers.

## Approval checklist

The reviewer needs to decide, per concept: keep, cut, or rename; and confirm that
each negative example really must not fire. The full list, so nothing is approved
by silence:

- [ ] `DOCTRINE_OFFER`
- [ ] `DOCTRINE_ACCEPTANCE`
- [ ] `DOCTRINE_CONSIDERATION`
- [ ] `DOCTRINE_CONTRACT_MODIFICATION`
- [ ] `DOCTRINE_PRE_EXISTING_DUTY` (and open question 1)
- [ ] `DOCTRINE_UNANTICIPATED_CIRCUMSTANCES`
- [ ] `DOCTRINE_BENEFIT_CONFERRED`
- [ ] `DOCTRINE_CHARTER_PROVISION`
- [ ] `DOCTRINE_CLAUSE_RESTATEMENT`
- [ ] `DOCTRINE_CITATION_REPORTER`
- [ ] `DOCTRINE_PROCEDURAL_POSTURE`
- [ ] `DOCTRINE_ISSUE_FRAMING`
- [ ] `DOCTRINE_HOLDING` (and open question 2)
- [ ] open question 3 (any `forbidden: true` doctrine concept)
- [ ] open question 4 (the API shape, and therefore the wire contract)
- [ ] open question 5 (whether the doctrine projection reaches the signed record)
- [ ] open question 6 (file name and vertical id)

## What happens after approval

Nothing in this section is done yet. Each step is the plan's, restated so the
sequence is visible:

1. **Author the lexicon** as `lexicons/legal-doctrine-v1.yaml` with the same
   structure the risk register uses (`version`, `runtime`, `concepts`, `lexicon`,
   `tests`), one `tests:` block per concept carrying the positives and negatives
   above.
2. **Add the second engine binding** in `interface/engine.py`, following the
   pattern `dossier_pipeline/governance/semantic_adapter.py::build_for_vertical`
   establishes: its own `lexicon_path`, `vertical_id`, `engine_class`, and its own
   `rules_hash`/`config_hash` read from `rules.hash`.
3. **Report both projections** per whichever shape is chosen in open question 4.
   The risk projection's existing output does not change, including its
   `admissible` field, which is what the risk register is for.
4. **Pin it in both directions:** the brief matches the doctrine concepts named in
   the coverage table above, and every negative example in this document still does
   not match. The second half is what stops the change from turning the coverage
   warning off forever.
5. **Record the hashes that moved.** The doctrine lexicon is new, so
   `rules_hash`/`config_hash` for the doctrine projection are new values; the risk
   register's hashes do not move, and a test should assert exactly that, since
   `W5`'s whole premise is that the risk register is untouched.
6. **Re-run the acceptance run.** `POST /evidence/{id}/analyse` exists so this can
   be done without re-uploading evidence, which would break custody. The expected
   result is the coverage warning clearing for this brief, with the negative
   examples still silent.

## What this draft does not change

For the avoidance of doubt, at the moment of writing:

- `lexicons/legal-v3.1.yaml` is unchanged, and its 23 concepts, 84 patterns and
  `rules_hash` are unchanged.
- `interface/engine.py` still loads exactly one lexicon, and `project_text` still
  returns a single risk projection.
- `interface/analysis.py`, `GET /evidence/{id}/analysis` and the coverage block are
  as implemented: one projection, with the warning that says 1 of 8 scopes matched.
- No engine semantics, no `admissible` value, and no consumer of
  `ProjectionResponse` has been affected.
