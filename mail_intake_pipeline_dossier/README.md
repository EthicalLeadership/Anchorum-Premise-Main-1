# Dossier DOSSIER-PIPELINE Evidence Governance Pipeline

Local, audit-grade evidence ingestion and classification system for the Client workplace/medical/insurance case.

## What This Does

- **Ingests** emails from ProtonMail Bridge IMAP (read-only, never marks as read)
- **Fingerprints** every email with SHA-256 cryptographic hashes
- **Classifies** by actor: Employer, Insurer, Union, Medical, Psychologist, Legal, Self, Unknown
- **Labels** legal risk: URGENT, LEGAL_SIGNIFICANT, PRESSURE_TACTIC, CONFLICT_MARKER, PRIVILEGED, etc.
- **Enforces** the Silence Matrix auto-quarantines employer pressure during protected leave
- **Chains** every decision into an immutable, hash-linked audit trail (SQLite)
- **Exports** tribunal-ready JSON + counsel-ready Markdown

## Operational Semantics

### Consistency model

The system uses a **control-plane canonical commit** model:

- **Control-plane commit defines canonical success**
- Seen-set, evidence store, outbound registry, and replay log are **derived stores / projections**
- Projection writes are durable and auditable, but they do **not** redefine canonical success
- If a downstream projection fails after control commit, the canonical record still exists

### Failure boundaries

- **Before control commit**: no canonical control record exists
- **After control commit**: canonical state exists, even if a projection write or export fails afterward
- **Policy rejection**: no canonical inbound control commit is made for the rejected message; quarantine artifacts are written instead

### Retry / idempotency rules

- Intake deduplication is keyed by normalized `Message-ID` and content fingerprint
- Retry after a successful control commit must **not** create a second canonical record for the same governed action
- Outbound sends are recorded with a single authoritative registry row and an associated control record
- Retryable failures are currently limited to top-level runtime failures (`process_email`) and should be treated as **best effort**, not transactional replay across all stores

## Architecture (8 Layers)

1. **Intake** MIME parsing, deduplication, cryptographic fingerprinting
2. **Classify** Deterministic actor/label detection (Quebec French + English)
3. **Provenance** Completeness checks, thread detection
4. **Adapt** Governance payload assembly with payload hash
5. **Policy** Hard enforcement boundaries (employer pressure → quarantine)
6. **Decide** Silence Matrix route derivation
7. **Control** Hash-linked audit chain (`previous_hash` → `record_hash`)
8. **Export** JSON manifest + Markdown summary

## Setup

### 1. Install ProtonMail Bridge

Download from [proton.me/mail/bridge](https://proton.me/mail/bridge) and install.

### 2. Log in to Bridge

- Open ProtonMail Bridge
- Log in with `client@example.com`
- Note the **mailbox password** Bridge generates (this is NOT your web password)

### 3. Configure Environment or JSON Config

```bash
cp dossier_pipeline/.env.example .env
# Edit .env and set PROTON_IMAP_PASSWORD to your Bridge mailbox password
```

Or create a JSON config file and pass it with `--config`:

```json
{
  "dossier": "DOSSIER-PIPELINE-LIVE",
  "output_dir": "/secure/output/path",
  "proton": {
    "host": "127.0.0.1",
    "port": 1143,
    "username": "your-address@protonmail.com",
    "password": "YOUR_BRIDGE_PASSWORD",
    "use_ssl": false,
    "mailbox": "INBOX"
  },
  "pipeline": {
    "batch_size": 50
  }
}
```

### 4. Test Connection

```bash
python3 - <<'PY'
import imaplib
c = imaplib.IMAP4("127.0.0.1", 1143)
print(c.welcome.decode(errors="replace"))
c.logout()
PY
```

If Bridge is not running locally, use direct IMAP (requires ProtonMail paid plan):

```bash
PROTON_IMAP_HOST=imap.protonmail.ch
PROTON_IMAP_PORT=993
PROTON_IMAP_USE_SSL=true
```

## Reproducibility

- Core pipeline logic (`dossier_pipeline/`, `dossier_enforcement/`, `ci/`) targets the Python standard library, but the project as a whole is **not** stdlib-only.
- Third-party dependencies are declared in `requirements.txt` (e.g. `SQLAlchemy`, `PyJWT`, `cryptography`, `cel-python`, `PyYAML`, `requests`) and, for the optional resident-AI layer, heavier packages (`chromadb`, `sentence-transformers`, `pymupdf`, `fpdf2`, `markdownify`). `pyproject.toml` declares the minimal runtime set (`SQLAlchemy`, `PyJWT`).
- There is currently **no lockfile**; `requirements.txt` uses unconstrained `>=` ranges, so installs are not byte-for-byte reproducible. See `docs/audit/INDEPENDENT_BUILD_AUDIT.md` (F-05/F-06).
- Runtime artifacts are stored locally under `output/`
- Re-running the pipeline on the same input should produce deterministic classifications, routes, and chain behavior, subject to timestamps in audit records

## Usage

### Run Demo (No ProtonMail required)

```bash
cd /mnt/agents/output
python -m dossier_pipeline.main demo
```

This processes 3 simulated emails (Employer pressure, Union, Medical) and exports results.

### Ingest from ProtonMail

```bash
python -m dossier_pipeline.main ingest-proton --limit 100
```

Using a JSON config file:

```bash
python -m dossier_pipeline.main --config ./config_live.json ingest-proton
```

### Ingest from Directory of .eml Files

```bash
python -m dossier_pipeline.main ingest-dir ./emails
```

### Verify Chain Integrity

```bash
python -m dossier_pipeline.main verify-chain
```

### Export Results

```bash
python -m dossier_pipeline.main export-json
python -m dossier_pipeline.main export-md
```

## Output Files

| File | Description |
|------|-------------|
| `DOSSIER-PIPELINE_export.json` | Machine-readable manifest with all records |
| `DOSSIER-PIPELINE_summary.md` | Human-readable summary for counsel review |
| `DOSSIER-PIPELINE_seen.db` | SQLite deduplication database |
| `DOSSIER-PIPELINE_chain.db` | SQLite hash-linked audit chain |

## Silence Matrix

| Actor + Condition | Route | Action |
|-------------------|-------|--------|
| Employer + PRESSURE_TACTIC | HOLD_SILENT | Do not respond. Document only. |
| Employer + REQUIRES_RESPONSE | QUARANTINE_REVIEW | Legal review before reply. |
| Insurer + LEGAL_SIGNIFICANT | QUARANTINE_REVIEW | Counsel review before disclosure. |
| Union | FORWARD_UNION | Forward to delegate and archive. |
| Medical + PRIVILEGED | QUARANTINE_REVIEW | Protect confidentiality. |
| Psychologist | QUARANTINE_REVIEW | High sensitivity review first. |
| Legal | ESCALATE_LEGAL | Immediate counsel escalation. |

## Deterministic Guarantee

This system uses **only** regex keyword matching and explicit heuristics. No machine learning. No opaque models. Every classification decision can be explained in court by showing the exact pattern that matched.

## Security

- **Read-only**: Never marks emails as read, never deletes, never sends replies.
- **Local-only**: No cloud dependencies. No Kafka, Neo4j, Redis.
- **Encrypted at rest**: SQLite databases stored locally with filesystem permissions.
- **Hash-linked**: Tampering with any record breaks the chain verifiable via `verify-chain`

## License

Built for Dossier DOSSIER-PIPELINE. Not for general distribution.
