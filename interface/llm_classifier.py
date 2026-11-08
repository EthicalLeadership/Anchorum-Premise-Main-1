"""LLM document classification and narrative generation via a local Ollama.

NON-DETERMINISTIC by nature. The classifier is a second opinion on documents the
deterministic classifier marks as "unknown"; it never overwrites `documentType`.
Both entry points cache by SHA-256 of (namespace, model, prompt) so a repeated
click is stable and costs nothing.

Fail-closed: any network error returns an `error` string without raising. A model
that is not running is a condition to report, not an exception to swallow into a
blank screen.

Every instruction comes from `interface.prompts`, which verifies the file against
`prompts/v1/manifest.json`. The registry can legitimately be unavailable — a
source tree copied without `prompts/` — so each prompt has a compact inlined
fallback and the result records which one was used. That keeps the feature
working while making the difference visible in the response rather than in a log
nobody reads.
"""

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from interface import prompts
import logging
from interface.citation_validator import validate_all_citations


def _ollama_url() -> str:
    """Read at call time so an operator can repoint a running process."""
    return os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")


def _model() -> str:
    return os.environ.get("CLF_MODEL", "llama3.1:8b")


def _cache_path() -> Path:
    return Path(os.environ.get("ANCHORUM_LLM_CACHE", "dev_data/llm_cache.json"))


#: Kept as module attributes for callers and tests that rebind them; the
#: functions above read the environment because a live process may be repointed.
OLLAMA_URL = _ollama_url()
LLM_MODEL = _model()
CACHE_PATH = _cache_path()

#: Document types the deterministic vocabulary can express. Kept short on
#: purpose: a suggestion outside this list is discarded, because a type the rest
#: of the system cannot act on is noise dressed as information.
ALLOWED = (
    "medical_note",
    "payroll",
    "insurer_letter",
    "official_report",
    "correspondence",
    "unknown",
)

#: Used when `prompts/v1/classify_document.txt` cannot be read. Deliberately the
#: same instruction, so behaviour degrades by provenance and not by output shape.
FALLBACK_CLASSIFY_PROMPT = (
    "Classify the following document as exactly one of: "
    "medical_note, payroll, insurer_letter, official_report, correspondence, unknown. "
    "Answer with only the single classification word, no punctuation, no explanation.\n\n"
    "Document:\n"
)

#: Used when `prompts/v1/analyze_claim.txt` cannot be read.
FALLBACK_SUMMARIZE_PROMPT = (
    "You are assisting a legal operator reading a document in a case file. "
    "Produce a concise factual summary in 3 to 5 sentences. State only what "
    "the document says. Do not offer legal advice. Do not speculate. If the "
    "document is too short or garbled to summarise, say so plainly.\n\n"
    "Document:\n"
)

#: The question the Saul button asks by default. It is passed through the
#: `{topic}` placeholder, which is what makes the same pinned prompt serve both
#: a summary and, later, a narrower review question.
DEFAULT_TOPIC = (
    "Résume ce document pour un dossier : ce qu'il établit, ce qu'il laisse "
    "manquant ou contradictoire, et ce qu'il implique pour la suite."
)


def _load_cache() -> dict:
    path = _cache_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(cache: dict) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=0), encoding="utf-8")
    except OSError:
        # A read-only cache directory must not fail the request: the answer was
        # already produced, and losing it only means the next call pays again.
        pass


def _cache_key(namespace: str, prompt: str) -> str:
    """Cache identity includes the model and the full prompt text.

    The model matters: the same document under two models is two answers, and a
    cache that ignored it would serve one as if it were the other. The prompt
    matters for the same reason once a prompt file is edited.
    """
    return hashlib.sha256(
        f"{namespace}\x00{_model()}\x00{prompt}".encode("utf-8")
    ).hexdigest()


def _parse(raw: str) -> str:
    lowered = raw.strip().lower()
    for word in ALLOWED:
        if word in lowered:
            return word
    return "unknown"


def _request(prompt: str, timeout: int) -> tuple[str | None, str | None]:
    """One call to the Ollama generate endpoint. Exactly one side is None."""
    body = json.dumps(
        {"model": _model(), "prompt": prompt, "stream": False}
    ).encode("utf-8")
    request = urllib.request.Request(
        _ollama_url(), data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return None, f"OLLAMA_UNREACHABLE: {type(exc).__name__}"
    if not isinstance(payload, dict):
        return None, "OLLAMA_BAD_RESPONSE: not a JSON object"
    text = payload.get("response", "")
    if not isinstance(text, str):
        return None, "OLLAMA_BAD_RESPONSE: response is not text"
    return text, None


def generate(prompt: str, *, namespace: str, timeout: int = 180) -> dict[str, Any]:
    """Run one prompt through the local model, with caching.

    This is the single place the interface talks to a model. The classifier, the
    claim extractor and the Saul narrator all go through it, so repointing
    OLLAMA_URL or changing CLF_MODEL moves every feature at once and no feature
    can quietly grow a client of its own.

    Shape::

        {"text": str, "backend": "ollama", "model": str,
         "cached": bool, "error": None | str}
    """
    if not prompt or not prompt.strip():
        return {
            "text": "",
            "backend": "ollama",
            "model": _model(),
            "cached": False,
            "error": "EMPTY_PROMPT",
        }

    key = _cache_key(namespace, prompt)
    cache = _load_cache()
    cached = cache.get(key)
    if isinstance(cached, dict) and isinstance(cached.get("text"), str):
        result = dict(cached)
        result["cached"] = True
        return result

    text, error = _request(prompt, timeout)
    result = {
        "text": "" if text is None else text,
        "backend": "ollama",
        "model": _model(),
        "cached": False,
        "error": error,
    }
    # Only a successful answer is cached. Caching a failure would make one
    # unreachable moment permanent for that text.
    if error is None:
        cache[key] = result
        _save_cache(cache)
    return result


def llm_classify(text: str) -> dict:
    """Return a document-type suggestion for a piece of text.

    Shape::

        {"documentType": str, "backend": "ollama", "model": str,
         "cached": bool, "error": None | "EMPTY_TEXT" | "OLLAMA_UNREACHABLE: …",
         "prompt": str}
    """
    if not text or not text.strip():
        return {
            "documentType": "unknown",
            "backend": "ollama",
            "model": _model(),
            "cached": False,
            "error": "EMPTY_TEXT",
            "prompt": "inline",
        }

    try:
        prompt = prompts.classify_document(text)
        prompt_origin = f"{prompts.CLASSIFY_DOCUMENT}@{prompts.VERSION}"
    except prompts.PromptError:
        prompt = FALLBACK_CLASSIFY_PROMPT + text
        prompt_origin = "inline"

    completion = generate(prompt, namespace="classify", timeout=120)
    
    # Validate citations in the response (Critical finding resolution)
    citation_report = validate_all_citations(completion["text"])
    if not citation_report["valid"]:
        logger.warning(
            "Citation validation failed for classify: %s. "
            "Invalid citations: %d, Warnings: %d",
            citation_report.get("invalid_citations", [{}])[0].get("error", "unknown"),
            len(citation_report["invalid_citations"]),
            citation_report["warning_count"],
        )

    return {
        # A failed call yields "unknown", not a guess: the deterministic
        # classifier's "unknown" is a statement that no rule matched, and
        # inventing a type here would make the two sources disagree silently.
        "documentType": (
            "unknown" if completion["error"] else _parse(completion["text"])
        ),
        "backend": "ollama",
        "model": completion["model"],
        "cached": completion["cached"],
        "error": completion["error"],
        "prompt": prompt_origin,
        "_citation_validation_report": citation_report,
    }


def llm_summarize(text: str, *, filename: str = "", topic: str = "") -> dict:
    """Run the Saul narrative prompt over one document's extracted text.

    The prompt is `prompts/v1/analyze_claim.txt`: a four-part analysis whose
    factual statements each carry a `[source: …]` citation. `{context}` receives
    the text, `{topic}` the question the reader is asking. When the registry is
    unavailable the fallback below is used and the result says so in `prompt`,
    so a reader is never shown a summary without being able to find out what
    produced it.

    Shape::

        {"narrative": str, "backend": "ollama", "model": str,
         "cached": bool, "error": None | "EMPTY_TEXT" | "OLLAMA_UNREACHABLE: …",
         "prompt": str, "promptSha256": str, "promptStatus": str}
    """
    if not text or not text.strip():
        return {
            "narrative": "",
            "backend": "ollama",
            "model": _model(),
            "cached": False,
            "error": "EMPTY_TEXT",
            "prompt": "inline",
            "promptSha256": "",
            "promptStatus": "empty_text",
        }

    context = text
    if filename.strip():
        # The citation format the prompt demands names a file, and the extracted
        # text carries no filename of its own. Telling the model which file it is
        # reading is the difference between a citation a reader can locate and
        # one that only looks like it.
        context = f"[fichier: {filename.strip()}]\n\n{text}"

    try:
        prompt = prompts.analyze_claim(context, topic=topic or DEFAULT_TOPIC)
        origin = prompts.describe(prompts.ANALYZE_CLAIM)
    except prompts.PromptError:
        prompt = FALLBACK_SUMMARIZE_PROMPT + context
        origin = {
            "prompt": "inline",
            "version": "",
            "sha256": "",
            "status": "missing",
        }

    completion = generate(prompt, namespace="summarize", timeout=240)
    
    # Validate citations in the response (Critical finding resolution)
    citation_report = validate_all_citations(completion["text"])
    if not citation_report["valid"]:
        logger.warning(
            "Citation validation failed for summarize: %s. "
            "Invalid citations: %d, Warnings: %d",
            citation_report.get("invalid_citations", [{}])[0].get("error", "unknown"),
            len(citation_report["invalid_citations"]),
            citation_report["warning_count"],
        )

    return {
        "narrative": completion["text"].strip(),
        "backend": "ollama",
        "model": completion["model"],
        "cached": completion["cached"],
        "error": completion["error"],
        "prompt": origin["prompt"],
        "promptSha256": origin["sha256"],
        "promptStatus": origin["status"],
        "_citation_validation_report": citation_report,
    }
