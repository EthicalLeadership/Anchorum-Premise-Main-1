"""LLM-based document type suggestion via a local Ollama endpoint.

NON-DETERMINISTIC by nature. It exists as a second opinion on documents the
deterministic classifier marks as "unknown". It never overwrites documentType.
Results are cached by SHA-256 of (prompt, text) so repeated clicks are stable.

Fail-closed: any network error returns {"documentType": "unknown", "error": ...}
without raising. Callers must not crash on it.
"""

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
LLM_MODEL = os.environ.get("CLF_MODEL", "llama3.1:8b")
CACHE_PATH = Path(os.environ.get("ANCHORUM_LLM_CACHE", "dev_data/llm_cache.json"))

PROMPT = (
    "Classify the following document as exactly one of: "
    "medical_note, payroll, insurer_letter, official_report, correspondence, unknown. "
    "Answer with only the single classification word, no punctuation, no explanation.\n\n"
    "Document:\n"
)

ALLOWED = (
    "medical_note",
    "payroll",
    "insurer_letter",
    "official_report",
    "correspondence",
    "unknown",
)


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=0), encoding="utf-8")


def _parse(raw: str) -> str:
    s = raw.strip().lower()
    for word in ALLOWED:
        if word in s:
            return word
    return "unknown"


def llm_classify(text: str) -> dict:
    """Return a suggestion dict for a piece of text.

    Shape:
        {
          "documentType": "medical_note" | ... | "unknown",
          "backend": "ollama",
          "model": str,
          "cached": bool,
          "error": None | "EMPTY_TEXT" | "OLLAMA_UNREACHABLE: ..."
        }
    """
    if not text or not text.strip():
        return {
            "documentType": "unknown",
            "backend": "ollama",
            "model": LLM_MODEL,
            "cached": False,
            "error": "EMPTY_TEXT",
        }

    key = hashlib.sha256((PROMPT + "\x00" + text).encode("utf-8")).hexdigest()
    cache = _load_cache()
    if key in cache and isinstance(cache[key], dict):
        cached = dict(cache[key])
        cached["cached"] = True
        return cached

    body = json.dumps(
        {"model": LLM_MODEL, "prompt": PROMPT + text, "stream": False}
    ).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            payload = json.loads(r.read())
            raw = payload.get("response", "") if isinstance(payload, dict) else ""
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {
            "documentType": "unknown",
            "backend": "ollama",
            "model": LLM_MODEL,
            "cached": False,
            "error": f"OLLAMA_UNREACHABLE: {type(exc).__name__}",
        }

    result = {
        "documentType": _parse(raw),
        "backend": "ollama",
        "model": LLM_MODEL,
        "cached": False,
        "error": None,
    }
    cache[key] = result
    try:
        _save_cache(cache)
    except OSError:
        pass
    return result

SUMMARIZE_PROMPT = (
    "You are assisting a legal operator reading a document in a case file. "
    "Produce a concise factual summary in 3 to 5 sentences. State only what "
    "the document says. Do not offer legal advice. Do not speculate. If the "
    "document is too short or garbled to summarise, say so plainly.\n\n"
    "Document:\n"
)


def llm_summarize(text: str) -> dict:
    """Return a summary of the given text.

    Shape:
        {
          "narrative": str,
          "backend": "ollama",
          "model": str,
          "cached": bool,
          "error": None | "EMPTY_TEXT" | "OLLAMA_UNREACHABLE: ..."
        }
    """
    if not text or not text.strip():
        return {
            "narrative": "",
            "backend": "ollama",
            "model": LLM_MODEL,
            "cached": False,
            "error": "EMPTY_TEXT",
        }

    key = hashlib.sha256((SUMMARIZE_PROMPT + "\x00" + text).encode("utf-8")).hexdigest()
    cache = _load_cache()
    cache_key = "summarize:" + key
    if cache_key in cache and isinstance(cache[cache_key], dict):
        cached = dict(cache[cache_key])
        cached["cached"] = True
        return cached

    body = json.dumps(
        {"model": LLM_MODEL, "prompt": SUMMARIZE_PROMPT + text, "stream": False}
    ).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            payload = json.loads(r.read())
            raw = payload.get("response", "") if isinstance(payload, dict) else ""
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return {
            "narrative": "",
            "backend": "ollama",
            "model": LLM_MODEL,
            "cached": False,
            "error": f"OLLAMA_UNREACHABLE: {type(exc).__name__}",
        }

    result = {
        "narrative": raw.strip(),
        "backend": "ollama",
        "model": LLM_MODEL,
        "cached": False,
        "error": None,
    }
    cache[cache_key] = result
    try:
        _save_cache(cache)
    except OSError:
        pass
    return result
