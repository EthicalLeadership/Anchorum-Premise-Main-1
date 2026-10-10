"""GRIC boundary inspector -- FastAPI server.

Five panels, read-only against committed repo state.
"""
from __future__ import annotations
import hashlib
import re
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from interface.engine import EngineUnavailable, lexicon_summary, project_text
from interface.gric.schemas import ProjectionRequest
from interface.document import process as document_process

REPO_ROOT = Path(__file__).resolve().parents[1]
INTERFACE_ROOT = Path(__file__).resolve().parent

app = FastAPI(title="Anchorum GRIC Inspector", version="0.1.0")
app.mount("/static", StaticFiles(directory=INTERFACE_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=INTERFACE_ROOT / "templates")


def read_manifest() -> dict:
    manifest_path = REPO_ROOT / "tests" / "fixtures" / "MANIFEST.sha256"
    out = {"path": str(manifest_path.relative_to(REPO_ROOT)),
           "exists": manifest_path.exists(), "rows": [], "summary": {}}
    if not manifest_path.exists():
        return out
    rows = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            rows.append({"expected": parts[0] if parts else "", "path": "",
                         "actual": None, "status": "malformed", "size": 0})
            continue
        expected, rel = parts[0].lower(), parts[1].strip()
        p = REPO_ROOT / rel
        if not p.exists():
            rows.append({"expected": expected, "path": rel, "actual": None,
                         "status": "missing", "size": 0})
            continue
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        rows.append({
            "expected": expected, "path": rel, "actual": actual,
            "size": p.stat().st_size,
            "status": "ok" if actual == expected else "mismatch",
        })
    out["rows"] = rows
    out["summary"] = {
        "total": len(rows),
        "ok": sum(1 for r in rows if r["status"] == "ok"),
        "missing": sum(1 for r in rows if r["status"] == "missing"),
        "mismatch": sum(1 for r in rows if r["status"] == "mismatch"),
    }
    return out


def read_tests() -> dict:
    regressions = REPO_ROOT / "tests" / "test_regressions.py"
    out = {"exists": regressions.exists(), "xfail_reasons": [],
           "total_markers": 0, "path": str(regressions.relative_to(REPO_ROOT))}
    if not regressions.exists():
        return out
    text = regressions.read_text(encoding="utf-8")
    for m in re.finditer(
        r"@pytest\.mark\.xfail\(reason=(['\"])(.+?)\1, strict=True\)", text
    ):
        out["xfail_reasons"].append(m.group(2))
    out["total_markers"] = len(out["xfail_reasons"])
    return out


def _parse_spec_fields(spec_path: Path) -> dict:
    """Extract status enum line and JSON field names from a GRIC spec."""
    result = {"exists": spec_path.exists(), "status_line": None, "fields": []}
    if not spec_path.exists():
        return result
    text = spec_path.read_text(encoding="utf-8")
    m = re.search(r'"status":\s*"([^"]+)"', text)
    if m:
        result["status_line"] = m.group(1)
    # JSON block with keys of the form "name":
    seen = set()
    for m in re.finditer(r'^\s{2}"([a-zA-Z_][a-zA-Z0-9_.]*)"', text, re.MULTILINE):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            result["fields"].append(name)
    return result


def read_gric_diff() -> dict:
    """Read drift table from CANONICAL.yaml and enrich with code/spec data."""
    import yaml
    from pathlib import Path
    
    # Load canonical spec
    canonical_path = Path(__file__).parent.parent / "contracts" / "CANONICAL.yaml"
    with open(canonical_path) as f:
        canonical = yaml.safe_load(f)
    
    # Parse code and spec for enrichment
    from dossier_pipeline.contracts import PipelineResult, ResultStatus
    contracts_status = sorted(s.value for s in ResultStatus)
    contracts_fields = sorted(PipelineResult.__dataclass_fields__)

    # Parse v1.0 and v1.1 specs for status lines
    v10_path = Path(__file__).parent.parent / "GRIC_v1.0_INTERFACE_SPEC.md"
    v11_path = Path(__file__).parent.parent / "GRIC_v1.1_INTERFACE_SPEC.md"
    
    def extract_status_line(filepath):
        if not filepath.exists():
            return None
        content = filepath.read_text(encoding="utf-8")
        import re
        match = re.search(r'"status":\s*"([^"]+)"', content)
        return match.group(1) if match else None
    
    v10_status_line = extract_status_line(v10_path)
    v11_status_line = extract_status_line(v11_path)

    # Build rows from canonical spec + code enrichment
    canonical_required = set(canonical["pipeline_result"]["required"])
    canonical_forbidden = set(canonical["pipeline_result"]["forbidden"])
    
    rows = []
    all_fields = sorted(set(contracts_fields))
    
    for f in all_fields:
        in_c = f in contracts_fields
        
        # Determine status based on canonical and code
        if f in canonical_required:
            if f in canonical_forbidden:
                status = "forbidden"
            elif f in contracts_fields:
                status = "aligned"
            else:
                status = "missing_from_code"
        elif f in canonical_forbidden:
            status = "forbidden"
        else:
            # Not in canonical - use legacy logic for backward compatibility
            v10_exists = v10_path.exists()
            v11_exists = v11_path.exists()
            
            if not v10_exists and not v11_exists:
                status = "removed"
            elif f in contracts_fields:
                status = "aligned"
            else:
                status = "drift"
        
        rows.append({
            "field": f,
            "v1_0": "present" if (v10_path.exists() and f in v10_path.read_text(encoding="utf-8")) else "-",
            "v1_1": "present" if (v11_path.exists() and f in v11_path.read_text(encoding="utf-8")) else "-",
            "contracts": "present" if in_c else "-",
            "status": status,
        })
    
    return {
        "v10_present": v10_status_line is not None,
        "v11_present": v11_status_line is not None,
        "v10_status_line": v10_status_line,
        "v11_status_line": v11_status_line,
        "contracts_status_line": " | ".join(contracts_status),
        "rows": rows,
    }


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return templates.TemplateResponse(request, "index.html", {"active": "home"})


@app.get("/manifest", response_class=HTMLResponse)
def manifest(request: Request):
    return templates.TemplateResponse(request, "manifest.html",
                                      {"active": "manifest", "data": read_manifest()})


@app.get("/lexicon", response_class=HTMLResponse)
def lexicon(request: Request):
    return templates.TemplateResponse(request, "lexicon.html",
                                      {"active": "lexicon", "data": lexicon_summary()})


@app.get("/tests", response_class=HTMLResponse)
def tests(request: Request):
    return templates.TemplateResponse(request, "tests.html",
                                      {"active": "tests", "data": read_tests()})


@app.get("/gric", response_class=HTMLResponse)
def gric(request: Request):
    try:
        data = read_gric_diff()
        error = None
    except Exception as e:
        data = {"rows": []}
        error = f"{type(e).__name__}: {e}"
    return templates.TemplateResponse(request, "gric.html",
                                      {"active": "gric", "data": data, "error": error})


@app.get("/project", response_class=HTMLResponse)
def project_form(request: Request):
    return templates.TemplateResponse(request, "project.html",
                                      {"active": "project", "text": "", "result": None, "error": None})


@app.post("/project", response_class=HTMLResponse)
def project_submit(request: Request, text: str = Form(...), vertical: str = Form("legal")):
    result = None
    error = None
    try:
        ProjectionRequest(text=text, vertical=vertical)
        result = project_text(text)
    except EngineUnavailable as e:
        error = f"engine unavailable: {e}"
    except ValueError as e:
        error = f"invalid input: {e}"
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    return templates.TemplateResponse(request, "project.html", {
        "active": "project", "text": text, "result": result, "error": error,
    })


@app.get("/document", response_class=HTMLResponse)
def document_form(request: Request):
    return templates.TemplateResponse(request, "document.html",
        {"active": "document", "result": None, "error": None})


@app.post("/document", response_class=HTMLResponse)
def document_submit(
    request: Request,
    text: str = Form(""),
    file: UploadFile | None = File(None),
):
    result = None
    error = None
    try:
        has_file = file is not None and bool(getattr(file, "filename", ""))
        if has_file:
            raw = file.file.read()
            name = (file.filename or "").lower()
            if name.endswith(".eml"):
                result = document_process(raw_bytes=raw)
            else:
                body = raw.decode("utf-8", errors="replace")
                result = document_process(text=body)
        elif text.strip():
            result = document_process(text=text)
        else:
            error = "Provide text or upload a file."
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    return templates.TemplateResponse(request, "document.html",
        {"active": "document", "result": result, "error": error})
