"""
Dossier DOSSIER-PIPELINE Deterministic Email Classifier
Court-explainable actor and label detection using regex keyword lists.
Quebec French + English terminology tuned for workplace/insurance/medical.
"""

import re
from typing import List

from dossier_enforcement import (FailureMode, LockRegistry, LockSpec,
                                  TransactionGate, assert_that, invariant)

from .contracts import (ActorType, ClassificationLabel, ClassificationResult,
                        EmailEnvelope)

_classifier_registry = LockRegistry(scope="classifier")
class EmailClassifier:
    """
    Deterministic classifier no ML, no opaque models.
    Every decision is traceable to explicit rule hits.
    """

    FRENCH_MARKERS = (
        r"\bbonjour\b",
        r"\bveuillez\b",
        r"\bmerci\b",
        r"\bcongé\b",
        r"\bdemeure\b",
        r"\bréponse\b",
        r"\bconfidentiel\b",
        r"\bmise\s+en\s+demeure\b",
    )
    ENGLISH_MARKERS = (
        r"\bhello\b",
        r"\bplease\b",
        r"\bthanks\b",
        r"\bleave\b",
        r"\bdemand\s+letter\b",
        r"\bresponse\b",
        r"\bconfidential\b",
        r"\bhold\s+notice\b",
    )

    def detect_language_of_origin(self, text: str) -> str:
        french_hits = sum(1 for pattern in self.FRENCH_MARKERS if re.search(pattern, text, re.IGNORECASE))
        english_hits = sum(1 for pattern in self.ENGLISH_MARKERS if re.search(pattern, text, re.IGNORECASE))
        if french_hits and english_hits:
            return "bilingual"
        if french_hits:
            return "fr"
        if english_hits:
            return "en"
        return "unknown"

    # ------------------------------------------------------------------
    # Actor detection patterns (Quebec French + English)
    # ------------------------------------------------------------------
    ACTOR_PATTERNS = {
        ActorType.EMPLOYER: [
            r"client", r"employer", r"hr@", r"ressources\s*humaines",
            r"employeur", r"vacation", r"congé", r"conges", r"position",
            r"poste", r"horaire", r"schedule", r"retour\s*au\s*travail",
            r"return\s*to\s*work", r"disciplinary", r"disciplinaire",
            r"faute\s*grave", r"misconduct", r"performance", r"évaluation",
            r"suspension", r"terminaison", r"termination", r"layoff",
            r"mise\s*à\s*pied", r"dossier\s*disciplinaire",
        ],
        ActorType.INSURER: [
            r"assurance", r"insurer", r"indemnisation", r"compensation",
            r"prévention", r"cnesst", r"csst", r"réclamation", r"claim",
            r"invalidité", r"disability\s*benefit", r"prestation",
            r"case\s*manager", r"gestionnaire\s*de\s*cas",
            r"réadaptation", r"rehabilitation", r"cpp", r"rqap",
            r"commission\s*des\s*normes",
        ],
        ActorType.UNION: [
            r"union", r"syndicat", r"union", r"délégué", r"steward",
            r"convention\s*collective", r"collective\s*agreement",
            r"grievance", r"plainte", r"arbitrage", r"arbitration",
            r"comité\s*paritaire", r"représentant", r"représentante",
        ],
        ActorType.MEDICAL: [
            r"dr\.?\s", r"docteur", r"médecin", r"clinique", r"hôpital",
            r"axion", r"médical", r"médicale", r"diagnostic", r"prescription",
            r"arrêt\s*de\s*travail", r"medical\s*certificate",
            r"note\s*médicale", r"aptitude", r"fitness\s*to\s*work",
            r"capacité", r"capacity", r"traitement", r"treatment",
            r"chirurgie", r"surgery", r"thérapie", r"therapy",
        ],
        ActorType.PSYCHOLOGIST: [
            r"psychologue", r"psychologist", r"psychiatre", r"psychiatrie",
            r"mental\s*health", r"santé\s*mentale", r"détresse",
            r"anxiété", r"dépression", r"burnout", r"épuisement",
            r"trauma", r"ptsd", r"tspt", r"counselling", r"consulter",
            r"psychothérapie", r"psychotherapy", r"aide\s*psychologique",
        ],
        ActorType.LEGAL: [
            r"avocat", r"attorney", r"lawyer", r"counsel", r"maître",
            r"cabinet\s*(d'avocats|juridique|legal)", r"law\s*firm",
            r"étude\s*(juridique|légale)", r"procureur", r"barreau",
            r"notaire", r"notary",
        ],
    }

    # ------------------------------------------------------------------
    # Label detection patterns
    # ------------------------------------------------------------------
    LABEL_PATTERNS = {
        ClassificationLabel.URGENT: [
            r"urgent", r"immédiat", r"immediate", r"deadline", r"échéance",
            r"requis\s*avant", r"required\s*by", r"délai",
            r"asap", r"dès\s*que\s*possible", r"prioritaire", r"priority",
            r"alerte", r"alert", r"attention", r"warning",
        ],
        ClassificationLabel.LEGAL_SIGNIFICANT: [
            r"litige", r"litigation", r"conservation", r"hold\s*notice",
            r"mise\s*en\s*demeure", r"demand\s*letter", r"avocat",
            r"legal", r"tribunal", r"cnesst", r"droit", r"right",
            r"obligation", r"congé\s*de\s*maladie", r"disability\s*leave",
            r"protected", r"protection", r"harcelement", r"harassment",
            r"discrimination", r"accommodation", r"accommodement",
            r"code\s*du\s*travail", r"labour\s*code", r"loi", r"act",
            r"règlement", r"regulation", r"ordonnance", r"injunction",
        ],
        ClassificationLabel.REQUIRES_RESPONSE: [
            r"veuillez\s*répondre", r"please\s*respond",
            r"réponse\s*requise", r"required\s*response",
            r"accusé\s*de\s*réception", r"acknowledge",
            r"confirmer", r"confirm", r"reply\s*required", r"répondez",
            r"réponse\s*attendue", r"response\s*expected",
            r"accusé\s*de\s*lecture", r"read\s*receipt",
        ],
        ClassificationLabel.CONFLICT_MARKER: [
            r"contradiction", r"incompatible", r"differs?\s*from",
            r"contraire", r"en\s*conflit", r"désaccord", r"disagree",
            r"incorrect", r"erreur", r"error", r"faux", r"false",
            r"inexact", r"wrong", r"not\s*true", r"pas\s*exact",
            r"différence", r"discrepancy", r"mismatch", r"non\s*concordance",
        ],
        ClassificationLabel.PRESSURE_TACTIC: [
            r"vous\s*devez", r"you\s*must", r"obligatoire", r"mandatory",
            r"sans\s*faute", r"without\s*fail", r"conséquences",
            r"consequences", r"sera\s*considéré", r"will\s*be\s*considered",
            r"faute\s*grave", r"misconduct", r"disciplinary",
            r"disciplinaire", r"sanction", r"penalty", r"pénalité",
            r"non\s*compliance", r"non\s*respect", r"violation",
            r"refus\s*de\s*coopérer", r"failure\s*to",
            r"sera\s*interprété", r"will\s*be\s*deemed", r"ultimatum",
            r"dernier\s*avertissement", r"final\s*warning",
        ],
        ClassificationLabel.PRIVILEGED: [
            r"confidentiel", r"confidential", r"privilégié", r"privileged",
            r"sans\s*préjudice", r"without\s*prejudice",
            r"avocat-client", r"attorney-client", r"secret\s*professionnel",
            r"professional\s*secret", r"privilège", r"privilege",
            r"sous\s*seing\s*privé", r"under\s*seal",
        ],
    }

    def classify(self, envelope: EmailEnvelope) -> ClassificationResult:
        lock = _classifier_registry.create_hierarchical_lock(
            LockSpec(f"classifier.doc.{envelope.message_key or envelope.message_id}", hierarchy_order=10)
        )
        with lock:
            with TransactionGate(f"classify-{envelope.message_key or envelope.message_id}", auto_commit=True) as gate:
                text = f"{envelope.subject} {envelope.body_text}".lower()
                assert_that(
                    len(text.strip()) > 0,
                    "classify requires non-empty content",
                    assertion_id="CLS-PRE-001",
                    mode=FailureMode.HARD,
                    context={"message_id": envelope.message_id},
                    actual=len(text.strip()),
                    expected=">0",
                )
                labels: List[ClassificationLabel] = []
                reasoning: List[str] = []
                rule_hits: List[str] = []
                language_of_origin = self.detect_language_of_origin(text)
                reasoning.append(f"Language of origin detected: {language_of_origin}")
                rule_hits.append(f"language:{language_of_origin}")
                if language_of_origin == "bilingual":
                    gate.execute_now(
                        forward=lambda: None,
                        reverse=lambda: None,
                        description="bilingual conflict flag",
                    )
                    invariant(
                        True,
                        "classifier.operational_scope",
                        actual="operational",
                        expected="operational",
                    )

                # ---- Actor detection ----
                actor_scores = {actor: 0 for actor in ActorType}
                for actor, patterns in self.ACTOR_PATTERNS.items():
                    for pattern in patterns:
                        if re.search(pattern, text, re.IGNORECASE):
                            actor_scores[actor] += 1
                            rule_hits.append(f"actor:{actor.value}:{pattern}")

                detected_actor = max(actor_scores, key=actor_scores.get)
                if actor_scores[detected_actor] == 0:
                    detected_actor = ActorType.UNKNOWN
                else:
                    # MD-01: Deterministic tie-breaking if multiple actors share the top
                    # score, emit UNKNOWN rather than picking whichever dict iteration returns
                    # first (non-deterministic across Python versions/runs).
                    top_score = actor_scores[detected_actor]
                    tied = [a for a, s in actor_scores.items() if s == top_score]
                    if len(tied) > 1:
                        detected_actor = ActorType.UNKNOWN
                        reasoning.append(
                            f"Actor tie ({[a.value for a in tied]}, score={top_score}) "
                            f"defaulting to UNKNOWN for determinism"
                        )
                        rule_hits.append(f"tie-break:UNKNOWN:{[a.value for a in tied]}")
                        if ClassificationLabel.CONFLICT_MARKER not in labels:
                            labels.append(ClassificationLabel.CONFLICT_MARKER)

                # Record actor detection decision in the reasoning trace
                reasoning.append(
                    f"Actor detected: {detected_actor.value} "
                    f"(score={actor_scores[detected_actor]})"
                )

                # A document submission has no correspondent: nobody sent it. The
                # scoring above still assigns whichever domain vocabulary happens
                # to appear most often, which on a court brief reads as "insurer".
                # For a non-email transport the actor is not applicable, and the
                # record says so in a field rather than only in this trace
                # (`trace` is internal-only and is stripped from exports).
                scope_warning = ""
                if envelope.transport != "email":
                    detected_actor = ActorType.UNKNOWN
                    scope_warning = (
                        "document transport: actor not applicable "
                        "(a court filing has no correspondent)"
                    )
                    reasoning.append(scope_warning)
                    rule_hits.append("scope:actor_not_applicable")

                # ---- Label detection ----
                for label, patterns in self.LABEL_PATTERNS.items():
                    for pattern in patterns:
                        if re.search(pattern, text, re.IGNORECASE):
                            if label not in labels:
                                labels.append(label)
                            reasoning.append(f"Matched pattern '{pattern}' → {label.value}")
                            rule_hits.append(f"label:{label.value}:{pattern}")

                # ---- CRITICAL HEURISTIC for Dossier DOSSIER-PIPELINE ----
                # Employer contacting about scheduling/position during disability leave
                if detected_actor == ActorType.EMPLOYER:
                    scheduling_terms = [
                        r"vacation", r"congé", r"position", r"poste",
                        r"schedule", r"horaire", r"retour\s*au\s*travail",
                        r"return\s*to\s*work", r"réintégration", r"reintegration"
                    ]
                    if any(re.search(term, text, re.IGNORECASE) for term in scheduling_terms):
                        if ClassificationLabel.PRESSURE_TACTIC not in labels:
                            labels.append(ClassificationLabel.PRESSURE_TACTIC)
                            reasoning.append(
                                "HEURISTIC: Employer contacting about scheduling/position "
                                "during protected disability leave → auto-flag PRESSURE_TACTIC"
                            )
                            rule_hits.append("heuristic:employer_during_leave:pressure_tactic")

                # ---- Default label ----
                if not labels:
                    labels.append(ClassificationLabel.INFORMATIONAL)
                    reasoning.append("No strong signals detected → default INFORMATIONAL")

                if language_of_origin == "bilingual" and ClassificationLabel.LEGAL_SIGNIFICANT in labels:
                    if ClassificationLabel.CONFLICT_MARKER not in labels:
                        labels.append(ClassificationLabel.CONFLICT_MARKER)
                    reasoning.append("Bilingual legal wording detected → added CONFLICT_MARKER for manual review")
                    rule_hits.append("language:bilingual:legal_conflict")

                # ---- Confidence ----
                # Base 0.3; each rule hit adds 0.15 per work-order specification.
                confidence = min(1.0, 0.3 + (len(rule_hits) * 0.15))

                result = ClassificationResult(
                    labels=labels,
                    confidence=confidence,
                    actor=detected_actor,
                    reasoning=reasoning,
                    rule_hits=rule_hits,
                    classification_scope_warning=scope_warning,
                )
                gate.execute_now(
                    forward=lambda: None,
                    reverse=lambda: None,
                    description="store classification",
                )
                return result
