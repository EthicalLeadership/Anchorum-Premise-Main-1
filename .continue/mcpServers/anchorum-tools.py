#!/usr/bin/env python3
"""MCP server: read, write, diff, verify_claim.
Every tool returns a typed result. No prose. The model cannot 'interpret' success."""
import hashlib, json, sys, difflib
from pathlib import Path

def result(ok, **kw):
    return json.dumps({"ok": ok, **kw})

def read_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return result(False, error="FILE_NOT_FOUND", path=path)
    if not p.is_file():
        return result(False, error="NOT_A_FILE", path=path)
    try:
        content = p.read_text(encoding="utf-8")
    except Exception as e:
        return result(False, error="READ_ERROR", detail=str(e))
    return result(True, path=path,
                    content=content,
                    sha256=hashlib.sha256(content.encode()).hexdigest(),
                    bytes=len(content))

def write_file(path: str, content: str, expected_sha256: str = None) -> str:
    p = Path(path)
    # Optimistic concurrency: refuse to clobber if file changed since read
    if p.exists() and expected_sha256 is not None:
        current = hashlib.sha256(p.read_text().encode()).hexdigest()
        if current != expected_sha256:
            return result(False, error="STALE_WRITE",
                         current_sha256=current,
                         expected_sha256=expected_sha256)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return result(True, path=path,
                  sha256=hashlib.sha256(content.encode()).hexdigest(),
                  bytes=len(content))

def diff(old_content: str, new_content: str) -> str:
    d = list(difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile="old", tofile="new", n=3))
    return result(True, diff="".join(d), changed=len(d))

def verify_claim(claim: str, artefact: str) -> str:
    """The core check: does the claim match the artefact?
    claim is a structured dict string with required fields."""
    try:
        c = json.loads(claim)
    except Exception:
        return result(False, error="CLAIM_NOT_JSON")
    ctype = c.get("type")
    if ctype == "line_present":
        line = c.get("line")
        ok = line in artefact
        return result(ok, check="line_present",
                      line=line, found=ok)
    if ctype == "line_absent":
        line = c.get("line")
        ok = line not in artefact
        return result(ok, check="line_absent",
                      line=line, absent=ok)
    if ctype == "field_added":
        field = c.get("field")
        ok = f'"{field}"' in artefact
        return result(ok, check="field_added",
                      field=field, found=ok)
    return result(False, error="UNKNOWN_CLAIM_TYPE", type=ctype)

# Minimal MCP stdio loop
TOOLS = {
    "read_file": read_file,
    "write_file": write_file,
    "diff": diff,
    "verify_claim": verify_claim,
}

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            print(json.dumps({"error": "bad json"}), flush=True)
            continue
        method = msg.get("method")
        if method == "tools/list":
            print(json.dumps({"tools": list(TOOLS.keys())}), flush=True)
        elif method == "tools/call":
            name = msg.get("name")
            args = msg.get("arguments", {})
            fn = TOOLS.get(name)
            if fn is None:
                print(result(False, error="UNKNOWN_TOOL", name=name), flush=True)
                continue
            try:
                print(fn(**args), flush=True)
            except TypeError as e:
                print(result(False, error="BAD_ARGS", detail=str(e)), flush=True)
        else:
            print(json.dumps({"error": "unknown_method"}), flush=True)

if __name__ == "__main__":
    main()
