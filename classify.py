"""Minimal classifier client. OpenAI-compatible chat endpoint.

Env:
  CLASSIFIER_URL    default http://127.0.0.1:8002/v1/chat/completions
  CLASSIFIER_MODEL  default kimi-k2-base
  CLASSIFIER_KEY    default "not-needed" (local endpoints ignore it)

CLI:
  python classify.py "sentence"
  echo "sentence" | python classify.py -
"""
import os, sys, json, urllib.request
from pathlib import Path

PROMPT_PATH = Path(__file__).parent / "classifier_prompt.txt"
DEFAULT_URL = os.environ.get("CLASSIFIER_URL",
                             "http://127.0.0.1:8002/v1/chat/completions")
DEFAULT_MODEL = os.environ.get("CLASSIFIER_MODEL", "kimi-k2-base")
DEFAULT_KEY = os.environ.get("CLASSIFIER_KEY", "not-needed")


def _load_prompt() -> str:
    return PROMPT_PATH.read_text().rstrip() + "\n"


def classify(text: str, *, url: str = DEFAULT_URL,
             model: str = DEFAULT_MODEL, api_key: str = DEFAULT_KEY,
             timeout: int = 30) -> str:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _load_prompt()},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "max_tokens": 4,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    raw = data["choices"][0]["message"]["content"].strip().upper()
    if "YES" in raw[:6]:
        return "YES"
    if "NO" in raw[:6]:
        return "NO"
    return "UNK:" + raw[:20]


if __name__ == "__main__":
    arg = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "-"
    text = sys.stdin.read().strip() if arg == "-" else arg
    try:
        print(classify(text))
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)
