
# ANCHORUM HQ Screen Map

**Status:** Product specification, version 1.0  
**Product posture:** Case intelligence and evidence-integrity platform for professional operators. This is not an autonomous legal-practice product.

## Product Workflow

Workflow: Case → Evidence → Intelligence → Validation → Strategy → Audit-ready Output

The Evidence Fabric is the system of record beneath the workflow. The War Room is the case workspace and decision surface; it is not a generic analytics dashboard. AI work is initiated as bounded jobs, and AI-generated material remains visibly distinct from source evidence and operator-approved material.

## Roles And Navigation

Primary navigation:

- **Workspace:** case list, recent activity, assigned tasks, deadlines, and alerts.
- **Cases:** create, find, and open cases.
- **Evidence:** case-scoped evidence search and intake.
- **Missions:** controlled analysis jobs and their results.
- **Legal Lens:** jurisdiction configuration and legal research material available to the tenant.
- **Admin:** members, roles, tenant policies, integrations, retention, and audit access.

A case opens with a persistent identity header, e.g. `DUPONT v. ACME`, jurisdiction, status, assigned team, and integrity/processing indicators. Case navigation:

- **War Room**
- **Evidence**
- **Timeline**
- **Intelligence**
- **Strategy**
- **Tasks**
- **Legal Lens**
- **Audit & Exports**
- **Case Settings**

Navigation is permission-filtered, but hiding a link is never an authorization control. Every API action independently checks tenant, case, role, and object policy.

## Screens And Interaction Contracts

### 1. Workspace / Case List

Purpose: resume work and identify next decisions. Show searchable cases with title/key, status, jurisdiction, owner/team, open tasks, next deadline, recent activity, and processing/integrity warnings. Filters include status, jurisdiction, owner, and deadline. Provide an explicit create-case action. Do not imply that activity counts or AI confidence are case truth.

States: first-use empty state; no search matches; loading; failed load with retry; permission-limited list; stale data indicator.

### 2. Create Case

Capture title, stable case key, jurisdiction, matter type, timezone, description, team, and optional initial parties/objectives. Validate required fields and uniqueness within the tenant. Explain the selected jurisdiction's source/version where configured. Creation is audited and returns to the new case War Room.

### 3. War Room

The first case screen answers six questions:

1. **What do we know?** Approved facts and claims with source citations.
2. **What don't we know?** Evidence gaps and unanswered questions.
3. **What might be wrong?** Contradictions, weak assumptions, and review flags.
4. **What could the opposing side argue?** Red Team assessment, clearly marked as AI-generated until reviewed.
5. **What should happen next?** Operator-owned tasks and Red DART's proposed, not autonomous, missions.
6. **What can be delivered?** Approved, provenance-complete material only.

Layout: case identity and status; concise next-actions/deadlines; evidence integrity and processing summary; timeline highlights; review queue; findings/gaps/contradictions; mission status; recent audited activity. Each item opens its source or review context. No unsupported aggregate score or decorative dashboard metrics.

States: no evidence yet; evidence processing; analysis unavailable; integrity verification required/failed; no findings; review queue; partial results; permissions restricted. An integrity failure is prominent and blocks affected analysis/export actions according to policy.

### 4. Case Details And People

Edit case metadata under role policy. Manage people/organizations as parties/entities with names, aliases, roles, and source-backed attributes. Distinguish a user-created assertion from an extracted AI entity. Merge/split operations preserve IDs, prior values, provenance, actor, reason, and audit history; never silently rewrite cited output.

### 5. Objectives, Notes, Tasks, And Deadlines

Manage case objectives and progress; add notes; create/assign tasks, due dates, dependencies, and status. Notes identify their author and creation time and may link evidence. Task changes are auditable. Deadline timezone and source are visible. AI may suggest a task from a gap or question but cannot create/assign it without operator confirmation.

### 6. Evidence Intake

Upload files or folders by picker or drag/drop. MVP formats: PDF, DOCX, common images, and email files/containers in explicitly supported formats. Show files, sizes, detected types, duplicate candidates, and upload/scan/index status. Before intake, show case destination and any applicable retention policy. Folder import reports each file independently and is resumable/idempotent.

A completed intake creates an Evidence ID and displays the SHA-256 of the exact original bytes, received timestamp and its source, uploader, custody event, immutable original status, metadata extraction status, and derived artifacts. A derivative or re-upload is never presented as the original. Unsupported, encrypted, malformed, malware-positive, or suspicious files enter a restricted/quarantined state with an actionable reason. Failed processing does not discard a successfully preserved original.

### 7. Evidence Register And Viewer

Table/list and filters: Evidence ID, filename, type, date range, people/entities, source, status, hash prefix, uploader, and custody/verification state. Full-text and semantic search results identify matched passage and page/offset where available.

Viewer separates **Original**, **Extracted text**, and **Derived artifacts**. Original access is read-only and records the applicable custody event. Show hash verification, versions/derivatives and parent links, parser version, metadata, provenance, and custody history. Corrections create a new event/version; they do not edit original bytes or erase old extraction results. Export/download is a permissioned audited action.

### 8. Search

Case-scoped search offers keyword/full-text and semantic modes, filters, sort, and evidence-type/date/person/source facets. Each result links to the exact evidence version and passage, with a clear distinction between indexed derivative and original. Search respects tenant and case authorization before retrieval/ranking. No-result, partial-index, stale-index, and unavailable-embedding states are explicit; lexical search remains available if semantic infrastructure is down.

### 9. Timeline

Chronological list with date, event, involved entities, source citations, extraction status, and reviewer state. Filter by date, person/entity, evidence, and event type. Opening an event reveals source passage and evidence viewer. Operators can correct date/text/entity links or reject an extracted event; record the prior value, actor, reason, and provenance. Never overwrite the source extraction. Uncertain dates and date precision (exact/range/relative/unknown) remain visible.

### 10. Intelligence Review

Tabs/filters for summaries, facts/claims, entities, contradictions, gaps, and investigation questions. Every candidate has a stable ID, type, exact citations to evidence/version/passage, model/prompt/configuration versions, creation time, confidence with a warning that confidence is not truth, and lifecycle status.

Review actions: accept/verify, edit into a new operator-authored version, reject with reason, request rerun, retract, or supersede. Show machine-generated, needs-review, human-verified, approved, rejected, retracted, and superseded as distinct states. High-impact output requires the policy-defined reviewer role and, where configured, a reviewer other than the author/requester. A finding without resolvable provenance cannot be accepted or exported.

### 11. Missions / Blue Team / Red Team

Operator selects a case, a question or claim, permitted evidence scope, and a typed mission. Blue Team assesses supporting evidence, missing support, and contradictions. Red Team tests opposing arguments, unsupported assumptions, and undermining facts. Red DART recommends/schedules only allow-listed analyses under policy; it does not invent facts, change evidence, authorize itself, or publish deliverables.

Before start, show scope, model/provider class, data handling boundary, expected outputs, and cost/quota estimate when available. Job states: queued, running, needs-input, completed, partially completed, failed, cancelled. Retries are visible and idempotent. Results use validated schemas and citations; invalid/uncited results are quarantined from findings. Operator may cancel permitted jobs. No opaque autonomous loops.

### 12. Legal Lens

Case jurisdiction and matter type are explicit. MVP plugin: Quebec/Canada labour matters, with modular jurisdiction/plugin boundaries. Show legal issue classifications as suggestions, applicable authority text/metadata, jurisdiction, effective/version dates, source and licensing/provenance, and citation resolution. Distinguish primary authority from secondary material and AI analysis. Do not generate a citation that is not in the configured source corpus. Legal interpretation is not represented as binding advice; review and source-validation state are visible.

### 13. Strategy

Strategy workspace contains operator-owned theories, options, assumptions, risks, questions, next steps, and draft paragraphs. Each material assertion links to approved findings/claims and then to evidence. Label unsupported assumptions and unresolved conflicts. AI can propose a draft or scenario analysis as a mission result; the operator must accept/edit it. Strategy versions and approvals are immutable transitions with author/reviewer, reason, and provenance snapshot.

### 14. Tasks And Review Queue

Combined personal/team queue for assigned tasks, deadlines, evidence processing requiring action, AI candidates awaiting review, failed jobs, and integrity alerts. Filters, assignment, due date, and status updates are audited. No silent assignment by agents.

### 15. Audit & Exports

Exports: case memo, evidence index, chronology, intelligence report, and audit package. Preview the exact included versions and review states; block or warn on unresolved citations, pending review, integrity failure, restricted evidence, or missing authorization. Each export includes a manifest of included artifacts, versions, hashes, source citations, generation/configuration metadata, actor, timestamp, and policy decision. Export creation/download is audited; sensitive export links expire and are scoped.

Audit view is filterable by actor, time, action, object, mission, and export. It displays append-only application events and evidence custody as separate records. A UI hash or chain indicator is not itself proof that storage is tamper-proof.

### 16. Admin And Tenant Settings

Member lifecycle and roles; case/team assignments; policy and retention configuration; jurisdiction plugins and authority sources; AI provider/model allow-list and data residency; secrets/integration status; audit access; export controls. Sensitive settings require reauthentication/strong role, change reason, and audit. Tenant configuration never leaks across organizations.

## Cross-Screen Rules

- Evidence access, preview, download, upload, verification, correction, export, approval, and mission execution are authorized server-side and audited.
- Every screen distinguishes source, derivative, machine-generated, operator-entered, verified, approved, and superseded content.
- Loading, retry, partial completion, quarantine, and integrity failure are first-class states; errors do not imply data loss or successful preservation.
- Citations resolve to immutable evidence identity/version and stable page/offset or an explicit unavailable-location reason.
- Confidence is presented as model output metadata, never a truth score.
- Tenant/case scope is persistent in navigation and visible in destructive/high-impact confirmations.
- Keyboard navigation, semantic labels, contrast, responsive layouts, and screen-reader announcements are required for intake, review, and mission flows.

## MVP Acceptance Walkthrough

A permitted operator creates a Quebec labour case, adds parties/objectives/tasks, imports a folder of representative PDFs/DOCX/images/email, and can see per-file preservation/hash/scan/index states. They search by text, person, date, and type; inspect a source-linked chronology; run a bounded Blue and Red mission; review/correct candidates; and export an approved memo, chronology, evidence index, and audit package. Every accepted assertion traces to evidence, every state transition identifies its actor, and a hostile/failed document is isolated without silently losing the original or corrupting other jobs.
