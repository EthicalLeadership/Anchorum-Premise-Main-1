# Anchorum-Prem Architecture Summary

## Overview

**Anchorum-Prem** is a customer-facing legal and audit toolkit for dossier processing, contract review, classification, and enforcement. It is a standalone Python product that does NOT import the `egregore` package.

---

## Technology Stack

### Backend (Python 3.12+)
- **Framework**: FastAPI + Uvicorn
- **ORM**: SQLAlchemy >=2.0,<3
- **Validation**: Pydantic >=2.0,<3
- **Security**: PyJWT, cryptography
- **Templates**: Jinja2
- **File Generation**: fpdf2

### Frontend (TypeScript/React)
- **Framework**: React 19.1.0
- **Build Tool**: Vite 6.3.5
- **Language**: TypeScript 5.8.3
- **Testing**: Vitest 4.1.11
- **Styling**: CSS modules

### Data & Storage
- **Database**: SQLAlchemy-backed (SQLite/PostgreSQL)
- **File System**: Dossier storage with integrity verification
- **Integrity**: SHA256 manifest verification

---

## Project Structure

```
anchorum-prem-main/
├── dossier_pipeline/          # Core pipeline logic
│   ├── main.py                # CLI entry point
│   ├── pipeline.py            # State machine orchestration
│   ├── control.py             # Control plane
│   ├── gateway.py             # External integrations
│   ├── evidence.py            # Evidence handling
│   ├── contracts.py           # Contract processing
│   └── ... (30+ modules)
├── dossier_enforcement/       # Enforcement layer
│   ├── gates.py               # Policy enforcement
│   ├── locks.py               # Locking mechanisms
│   └── assertions.py          # Assertion validation
├── interface/                 # Frontend + API server
│   ├── server.py              # FastAPI server
│   ├── src/                   # React application
│   │   ├── App.tsx           # Main app component
│   │   ├── adapter.ts         # Backend communication
│   │   ├── components/        # UI components
│   │   └── screens/           # Screen layouts
│   └── templates/             # Jinja2 templates
├── config/                    # Configuration files
├── tests/                     # Test suite
├── docs/                      # Documentation
├── ccsp/                      # Canonical Concept System
├── ci/                        # CI/CD scripts
└── ... (other modules)
```

---

## Key Architectural Patterns

### 1. Plane Discipline
- **Plane 1 (Kernel/Application)**: Deterministic logic, no wall-clock time
- **Plane 2 (Infrastructure/API)**: Projections of Plane 1 truth

### 2. State Machine
- Dossier pipeline follows a defined state machine with transitions
- Each transition is logged and auditable
- State persistence via SQLAlchemy models

### 3. Evidence Chain
- All evidence items have cryptographic hashes
- Integrity verified against manifest files
- Quarantine mechanisms for suspicious items

### 4. Actor Model
- System actors classified by JSON config
- Neutral placeholders in example configs
- No client data in examples

---

## Entry Points

### CLI
```bash
python -m dossier_pipeline.main ingest-proton --limit 100
python -m dossier_pipeline.main ingest-dir ./emails
python -m dossier_pipeline.main export-json
python -m dossier_pipeline.main verify-chain
python -m dossier_pipeline.main demo
python -m dossier_pipeline.main enforce
```

### Web Interface
- **Server**: `interface/server.py` (FastAPI)
- **Frontend**: Served from `/src/` via Vite build
- **Routes**:
  - `/` → Home dashboard
  - `/#/cases` → Case list
  - `/#/admin` → Administration
  - `/project` → Text classification
  - `/document` → Document processing

---

## Dependencies

### Runtime (requirements.txt)
```
SQLAlchemy>=2.0,<3
PyJWT>=2.8,<3
fastapi>=0.110,<1
uvicorn>=0.30,<1
pydantic>=2.0,<3
jinja2>=3.1,<4
python-multipart>=0.0.9,<0.1
cel-python>=0.5,<1
PyYAML>=6.0,<7
cryptography>=42.0,<51
fpdf2>=2.7,<3
```

### Development (requirements-dev.txt)
- pytest and test utilities

### Frontend (interface/package.json)
```json
{
  "dependencies": {
    "react": "^19.1.0",
    "react-dom": "^19.1.0"
  },
  "devDependencies": {
    "typescript": "^5.8.3",
    "vite": "^6.3.5",
    "vitest": "^4.1.11"
  }
}
```

---

## Important Notes

### Determinism Contract
- Never answer factual questions without bank citation
- When retrieval returns no hits, return UNKNOWN
- Every inference event must record model_hash, prompt_hash, bank_versions[]
- Never claim determinism for an answer you cannot replay

### Security Boundaries
- GRIC (Generalized Risk Inspection Component) boundary inspector
- Five-panel read-only inspection mode
- Manifest verification for file integrity

### License
**Proprietary and Confidential.** Copyright (c) 2026 Egregore AI. All Rights Reserved.

---

## Related Projects (NOT imported)

- **Full Egregore**: `~/Egregore-Deterministic-Epistemic-Global-Mesh-main/`
- **Client Egregore**: `~/Desktop/Egregore_Anchorum_client/egregore/`
- **Mozilla Hindsight**: Unrelated Lua telemetry processor

---

## Quick Start

```bash
# Install runtime dependencies
pip install -r requirements.lock

# Install development dependencies
pip install -r requirements-dev.txt

# Run the pipeline
python -m dossier_pipeline.main demo

# Start the web interface
cd interface && npm run dev
```

