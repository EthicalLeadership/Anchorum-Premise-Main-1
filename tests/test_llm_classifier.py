import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from interface import llm_classifier


@pytest.fixture(autouse=True)
def _reset_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHORUM_LLM_CACHE", str(tmp_path / "cache.json"))
    monkeypatch.setattr(llm_classifier, "CACHE_PATH", tmp_path / "cache.json")
    yield


def _mock_ollama(response_text: str):
    payload = json.dumps({"response": response_text}).encode()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=io.BytesIO(payload))
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def test_llm_classify_returns_expected_type():
    with patch("urllib.request.urlopen", return_value=_mock_ollama("medical_note")):
        result = llm_classifier.llm_classify("Ordonnance du medecin.")
    assert result["documentType"] == "medical_note"
    assert result["backend"] == "ollama"
    assert result["cached"] is False
    assert result["error"] is None


def test_llm_classify_fails_closed_on_network_error():
    err = urllib.error.URLError("connection refused")
    with patch("urllib.request.urlopen", side_effect=err):
        result = llm_classifier.llm_classify("Some text")
    assert result["documentType"] == "unknown"
    assert result["error"].startswith("OLLAMA_UNREACHABLE")


def test_llm_classify_empty_text_short_circuits():
    result = llm_classifier.llm_classify("   ")
    assert result["documentType"] == "unknown"
    assert result["error"] == "EMPTY_TEXT"


def test_llm_classify_caches_second_call():
    with patch("urllib.request.urlopen", return_value=_mock_ollama("payroll")):
        first = llm_classifier.llm_classify("Payroll summary.")
    with patch("urllib.request.urlopen", side_effect=AssertionError("should not call")):
        second = llm_classifier.llm_classify("Payroll summary.")
    assert second["documentType"] == "payroll"
    assert second["cached"] is True


def test_llm_classify_parses_loose_model_output():
    # Model answers with extra words; parser still extracts the type.
    with patch(
        "urllib.request.urlopen",
        return_value=_mock_ollama("This is a medical_note document."),
    ):
        result = llm_classifier.llm_classify("Dr. Smith.")
    assert result["documentType"] == "medical_note"


def test_llm_summarize_returns_narrative():
    with patch("urllib.request.urlopen", return_value=_mock_ollama("This is a summary. It has three sentences.")):
        result = llm_classifier.llm_summarize("Full document text.")
    assert result["narrative"].startswith("This is a summary")
    assert result["error"] is None


def test_llm_summarize_empty_short_circuits():
    result = llm_classifier.llm_summarize("   ")
    assert result["narrative"] == ""
    assert result["error"] == "EMPTY_TEXT"


def test_llm_summarize_fails_closed():
    err = urllib.error.URLError("connection refused")
    with patch("urllib.request.urlopen", side_effect=err):
        result = llm_classifier.llm_summarize("Some text")
    assert result["narrative"] == ""
    assert result["error"].startswith("OLLAMA_UNREACHABLE")
