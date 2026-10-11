# GRIC to Anchorum Prem Main: merge decision

Status: decided 2026-10-10. Supersedes any prior assumption about which
interface is the shell.

## Decision

**Anchorum Prem Main is the product and the API shell.**
GRIC is not a product. GRIC's read-only inspector routes are not the
interface. GRIC's logic is absorbed as a library that Prem Main calls.

## What this means concretely

1. The FastAPI app is `interface/server.py`, but its route surface is
   rewritten to Prem Main's domain. GRIC routes at `/manifest`,
   `/lexicon`, `/tests`, `/gric`, `/project`, `/document` are removed
   from the root namespace.

2. GRIC's logic (`interface/document.py::process`,
   `interface/engine.py::lexicon_summary` and `project_text`,
   `interface/gric/schemas.py`) is kept as importable modules. Nothing
   about the pipeline integration is thrown away.

3. New root routes belong to Prem Main's MVP:
   - `/` : case list
   - `/cases` : create case, list cases
   - `/cases/{id}` : War Room for one case
   - `/cases/{id}/evidence` : upload, list, view
   - `/cases/{id}/timeline` : extracted chronology
   - `/cases/{id}/search` : full-text and filtered search
   - `/cases/{id}/export` : case memo, evidence index, audit package

4. GRIC's inspector, if still wanted, moves to `/internal/gric/*` and
   is treated as a developer-only surface, not part of the product UI.

## What is not decided here

- The storage model. `docs/product/DATA_MODEL.md` governs.
- The AI layer. `docs/product/SYSTEM_ARCHITECTURE.md` governs.
- The screen inventory. `docs/product/SCREEN_MAP.md` governs.
- The build order. `docs/product/MVP_BACKLOG.md` governs.

This file is only about which shell exists and what happens to GRIC.

Author: Samuel Tessier
