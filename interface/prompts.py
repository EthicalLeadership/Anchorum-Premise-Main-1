"""Versioned prompt registry for the `prompts/` tree.

Every instruction the interface sends to a model comes from a file here rather
than from a string literal inside a module. The reason is narrow and practical:
when a reader asks what produced an answer, the answer is "the text of
`prompts/v1/analyze_claim.txt`, whose SHA-256 is pinned in `manifest.json`" —
a claim someone can check. A prompt inlined in Python is a claim nobody can.

A file that does not hash to its manifest entry is refused, not loaded. A prompt
that silently changed is a different instruction, and the answer it produced is
not comparable to the one before it.

The registry never raises at import time. A missing `prompts/` directory is a
packaging fault that must show up as an honest `PromptUnavailable` at the call
site, not as an import error that takes the whole application down.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Mapping

#: Repository root; `prompts/` sits beside `interface/` and `dossier_pipeline/`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPT_ROOT = PROJECT_ROOT / "prompts"

#: The prompt version this build reads. Bumping it is a deliberate act: an
#: answer produced under v1 is not comparable to one produced under v2.
VERSION = "v1"
PROMPT_DIRECTORY = PROMPT_ROOT / VERSION
MANIFEST_PATH = PROMPT_DIRECTORY / "manifest.json"

#: `{name}` placeholders. Only bare identifiers count, so a prompt may contain
#: braces that are not placeholders without breaking interpolation.
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class PromptError(RuntimeError):
    """Base class: the prompt could not be used, and the caller must say so."""


class PromptUnavailable(PromptError):
    """The prompt file or its manifest is missing from this build."""


class PromptIntegrityError(PromptError):
    """The prompt file no longer matches the hash recorded for it."""


def _read_manifest() -> dict[str, str]:
    """The `name -> sha256` map, or an empty map when none can be read.

    A missing manifest is not treated as "no verification needed": `load`
    refuses a file the manifest does not mention, so an absent manifest means
    every prompt is refused. That is the fail-closed direction.
    """
    try:
        parsed = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(name): str(digest)
        for name, digest in parsed.items()
        if isinstance(name, str) and isinstance(digest, str)
    }


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(name: str) -> str:
    """Return the verified text of one prompt file.

    Raises `PromptUnavailable` when the file or its manifest entry is absent,
    and `PromptIntegrityError` when the bytes on disk disagree with the pinned
    digest.
    """
    manifest = _read_manifest()
    expected = manifest.get(name)
    if expected is None:
        raise PromptUnavailable(
            f"prompt {name!r} is not pinned in {MANIFEST_PATH.name} for {VERSION}"
        )
    path = PROMPT_DIRECTORY / name
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PromptUnavailable(f"prompt {name!r} could not be read: {exc}") from exc
    actual = _digest(data)
    if actual != expected:
        raise PromptIntegrityError(
            f"prompt {name!r} hashes to {actual}, manifest pins {expected}"
        )
    return data.decode("utf-8")


def render(name: str, values: Mapping[str, object]) -> str:
    """Fill `{placeholder}`s in a prompt.

    A placeholder with no supplied value is left standing rather than replaced
    with an empty string. A prompt that asks the model to analyse `{topic}` and
    receives "" asks a different question; leaving the token visible makes the
    omission obvious in the prompt and in whatever the model returns.
    """
    text = load(name)

    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            return match.group(0)
        return str(values[key])

    return _PLACEHOLDER.sub(substitute, text)


def describe(name: str) -> dict[str, str]:
    """Provenance for one prompt, for the record that carries an answer.

    Never raises: a record describing an unavailable prompt must still be able
    to say which prompt was meant.
    """
    try:
        data = (PROMPT_DIRECTORY / name).read_bytes()
    except OSError:
        return {"prompt": name, "version": VERSION, "sha256": "", "status": "missing"}
    expected = _read_manifest().get(name)
    actual = _digest(data)
    if expected is None:
        status = "unpinned"
    elif expected == actual:
        status = "verified"
    else:
        status = "changed"
    return {"prompt": name, "version": VERSION, "sha256": actual, "status": status}


# --------------------------------------------------------------------------
# The named prompts this build sends.
# --------------------------------------------------------------------------

#: `analyze_claim.txt` asks for a four-part French analysis in which every
#: factual statement carries a `[source: …]` citation. That citation format is
#: what lets the interface check the narrative against the document instead of
#: asking a reader to trust prose.
ANALYZE_CLAIM = "analyze_claim.txt"
CLASSIFY_DOCUMENT = "classify_document.txt"
EXTRACT_CLAIMS = "extract_claims.txt"
VALIDATE_CITATION_SUPPORT = "validate_citation_support.txt"
SUMMARIZE_EMAIL = "summarize_email.txt"
SYSTEM = "system.txt"

#: The topic line handed to `analyze_claim.txt` when a caller does not supply a
#: narrower question. It names the task the button performs, so the analysis
#: comes back aimed at a summary rather than at an open-ended review.
DEFAULT_TOPIC = (
    "Résume ce document pour un dossier : ce qu'il établit, ce qu'il laisse "
    "manquant ou contradictoire, et ce qu'il implique pour la suite."
)


def analyze_claim(context: str, *, topic: str = "") -> str:
    """The Saul narrative prompt for one document's extracted text."""
    return render(
        ANALYZE_CLAIM,
        {"context": context, "topic": topic.strip() or DEFAULT_TOPIC},
    )


def validate_citation_support(narrative: str) -> str:
    """Ask the model for source quotes supporting a generated narrative."""
    return render(
        VALIDATE_CITATION_SUPPORT,
        {"narrative": narrative},
    )


def claim_instructions(*, mode: str, contract_type: str) -> str:
    """The standing rules plus the claim-extraction task, without the document.

    The document is appended by the caller immediately before sending, so the
    instructions never precede nothing and a prompt is never sent twice with
    different content under the same cache namespace.
    """
    return f"{system()}\n\n{render(EXTRACT_CLAIMS, {'mode': mode, 'contract_type': contract_type or 'n/a'})}"


def classify_document(text: str) -> str:
    """The second-opinion classifier prompt for one document's text."""
    return render(CLASSIFY_DOCUMENT, {"text": text})


def summarize_email(email_text: str) -> str:
    return render(SUMMARIZE_EMAIL, {"email_text": email_text})


def system() -> str:
    return load(SYSTEM)
