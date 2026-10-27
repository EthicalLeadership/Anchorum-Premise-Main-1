import { fixture } from "./fixtures/dupont-v-acme";

import type { CaseSummary, SessionUser } from "./types";

export interface AdapterConfig {
  backend: { baseUrl: string } | null;
  searchIndexReady?: boolean;
}

export interface CaseCreateInput {
  key: string;
  title: string;
  jurisdiction: string;
  matterType: string;
  timezone: string;
  description: string;
  memberIds: string[];
}

export type CreateCaseInput = CaseCreateInput;
export type CreateCaseResult =
  | { ok: true; value: { id: string; key: string } }
  | { ok: false; error: "CASE_KEY_TAKEN" | "BACKEND_UNREACHABLE" };

export type AdapterResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string };

export type CustodyEntry = {
  id: string;
  actor: string;
  action: string;
  at: string;
  chain: string;
  failingStep?: string | null;
  /** HMAC of this row's record_hash (Wire 4). Empty string when the
   *  deployment has no GDC_EVIDENCE_SECRET configured — the row was written
   *  unsigned, and the metadata block must say so rather than show a blank. */
  hmac?: string;
};
/**
 * What analysis did to an artifact's bytes, as the API reports it. This is the
 * real vocabulary, not a two-value approximation of it: `unsupported` means the
 * connector refused the artifact type rather than reading it, and `failed`
 * means it tried and did not succeed. Collapsing those into "done" would tell a
 * reader the opposite of what happened.
 */
export type ExtractStatus =
  | "stored"
  | "extracted"
  | "unsupported"
  | "empty"
  | "skipped_oversize"
  | "failed";

/** The item-level status the API maps `ExtractStatus` onto. */
export type EvidenceStatus =
  | "received"
  | ExtractStatus
  | "processed";

/**
 * What analysis extracted from an artifact.
 *
 * `status` travels with the text because "we read it and found nothing" and
 * "we never read it" both produce a null `text`, and a reader shown a blank
 * pane cannot tell which happened. An unsupported file is not an empty one.
 */
export type EvidenceText = {
  id: string;
  status: ExtractStatus;
  chars: number;
  sha256: string;
  reason: string;
  text: string | null;
  truncated: boolean;
};

/** The analysis-status vocabulary the analysis route reports. */
export type AnalysisStatus =
  | "pending"
  | "processed"
  | "unsupported"
  | "empty"
  | "skipped_oversize"
  | "failed";

/** The compact analysis view carried by every evidence item. */
export type EvidenceAnalysis = {
  status: AnalysisStatus | string;
  scopesTotal: number;
  scopesMatched: number;
  warning: string | null;
  analysedAt: string | null;
  documentType?: string | null;
  metadata?: { date?: string | null; author?: string | null; issuer?: string | null } | null;
};

export type EvidenceFilters = {
  status?: string;
  category?: string;
  source?: string;
  documentType?: string;
  author?: string;
  date?: string;
};

export type Evidence = {
  id: string;
  name: string;
  // The server sends one of `EvidenceStatus`. The offline fixtures carry their
  // own labels ("preserved", "integrity_hold") because they stand in for a
  // backend that is not running, so this stays wider than the wire vocabulary.
  status: string;
  badges: readonly string[];
  analysis?: EvidenceAnalysis | null;
  quarantinedReason: string | null;
  holdReason: string | null;
  duplicateCandidate: boolean;
  category?: string | null;
  source?: string | null;
  consultation?: Consultation | null;
  /** SHA-256 of the original file bytes (server: document.content_hash).
   *  Optional because older fixtures and some statuses don't carry it. */
  sha256?: string;
};
/** The second-opinion document type the AI consultant returned, if any. */
export type Consultation = {
  documentType: string;
  backend?: string;
  model?: string;
  cached?: boolean;
  error?: string | null;
  prompt?: string;
};

/**
 * One claim the narrator made, and whether its quote was found in the document.
 *
 * `span_normalized` is the position of the quote in the whitespace-collapsed
 * text. It travels because a reader checking a claim needs to know where to
 * look, not only that someone checked.
 */
export type SummaryClaim = {
  text: string;
  quote: string | null;
  basis: "explicit" | "absence";
  confidence: "direct" | "inferred";
  source: {
    quote: string | null;
    span_normalized: [number, number] | null;
    match?: string;
  };
};

/**
 * What verification did with the claims.
 *
 * `notRun` is present only when the model produced no narrative at all: then
 * nothing was checked, and reporting zero verified claims would read as "the
 * model said nothing worth quoting" instead of "the check did not happen".
 */
export type SummaryValidation = {
  verified: number;
  inferred: number;
  rejected: number;
  total: number;
  rejected_claims: Array<{
    claim_text: string;
    attempted_quote: string;
    reason: string;
  }>;
  notRun?: string;
};

export type SummaryNarrative = {
  narrative: string;
  model?: string;
  cached?: boolean;
  error?: string | null;
  prompt?: string;
  promptStatus?: string;
};

export type SummaryResult = {
  id: string;
  narrative: SummaryNarrative | null;
  claims: SummaryClaim[];
  validation: SummaryValidation | null;
  generatedAt?: string;
  cached?: boolean;
  reason?: string;
  message?: string;
};

export interface IngestInput {
  name: string;
  size: number;
  type: string;
  bytes: ArrayBuffer;
  category?: string | null;
  source?: string | null;
}
export type IngestResult =
  | {
      ok: true;
      value: {
        id: string;
        hash: string;
        sourceSha256: string;
        duplicate: boolean;
        processingStatus?: ExtractStatus;
        analysis?: EvidenceAnalysis | null;
        category?: string | null;
        source?: string | null;
      };
    }
  | {
      ok: false;
      error: string;
      failedStage?: "received" | "preserved" | "scanned" | "indexed";
    };
const sessionEvidence: Array<Evidence & { hash: string }> = [];
async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
type Verification = (typeof fixture.verification)[keyof typeof fixture.verification];
/**
 * One pre-flight gate. `blocking` decides what a failure means: a blocking
 * failure stops the export, an advisory one is recorded and reported. `warn`
 * is not "fail" — it is the normal state of evidence whose date the extractor
 * could not read, and collapsing the two would either block every export or
 * hide the warning.
 */
export type ExportGate = {
  id: string;
  result: "pass" | "fail" | "not_checked" | "warn";
  blocking?: boolean;
  failingItem: string | null;
  detail?: string;
};
type ExportPreview = {
  type: string;
  gates: readonly ExportGate[];
  blocked: boolean;
};
/**
 * One cryptographic claim re-derived by the server. `code` is machine-readable
 * so the interface can phrase the outcome in the reader's language; `status`
 * distinguishes "verified" from "could not be checked", which are not the same
 * statement and must not be rendered as one.
 */
export type ProofResult = {
  id: string;
  status: "pass" | "fail" | "not_checked";
  code: string;
  failingItem: string | null;
  checked: number;
};
export type ProofsReport = {
  caseId: string;
  status: "pass" | "fail" | "not_checked";
  verifiedAt: string;
  proofs: readonly ProofResult[];
};
/**
 * A case's public anchor.
 *
 * `stale` is the field that carries the point of the feature: the digest
 * published to DNS and the digest the evidence produces today are both here,
 * so a reader can see them disagree instead of trusting a stored "anchored".
 */
export type AnchorState = {
  anchored: boolean;
  configured: boolean;
  expectedName?: string;
  digest?: string;
  recordName?: string;
  recordContent?: string;
  publishedAt?: string;
  currentDigest?: string;
  stale?: boolean;
};
export type AuditEntry =
  | (typeof fixture.audit)[number]
  | {
      id: string;
      event: "member_role_changed";
      evidenceId: null;
      chain: "linked";
      memberId: string;
      actor: string;
      previousRole: SessionUser["role"];
      role: SessionUser["role"];
      reason: string;
      at: string;
    };
/**
 * One search hit. `offset` and `line` are the match's position in the
 * extracted text: without them a hit in a forty-page exhibit says what was
 * found but not where, and "open the document" means "look for it again".
 */
type SearchResult = {
  id: string;
  excerpt: string;
  offset?: number;
  line?: number;
};
export type TimelineEvent = (typeof fixture.timeline)[number];

function success<T>(value: T): AdapterResult<T> {
  return { ok: true, value };
}

function failure(error: string): AdapterResult<never> {
  return { ok: false, error };
}

function namedError(value: unknown, fallback: string): string {
  if (
    typeof value === "string" &&
    /^[A-Z][A-Z0-9_]+$/.test(value)
  ) {
    return value;
  }
  return fallback;
}

async function request<T>(
  baseUrl: string,
  path: string,
  init?: RequestInit,
): Promise<AdapterResult<T>> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl.replace(/\/$/, "")}${path}`, init);
  } catch {
    return failure("BACKEND_UNREACHABLE");
  }

  if (!response.ok) {
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      return failure(`HTTP_${response.status}`);
    }
    const error =
      typeof payload === "object" && payload !== null && "error" in payload
        ? payload.error
        : undefined;
    return failure(namedError(error, `HTTP_${response.status}`));
  }

  try {
    const value: unknown = await response.json();
    return success(value as T);
  } catch {
    return failure("INVALID_BACKEND_RESPONSE");
  }
}

export interface CaseRow {
  id: string;
  key: string;
  title: string;
  status: "open" | "closed" | "on_hold";
  ownerId: string;
  evidenceCount: number;
  holdCount: number;
  lastActivity: string;
  timezone: string;
}

/** One stage of the email intake pipeline, as the interface draws it. */
export type IntakeStage = {
  id: "received" | "classified" | "policy";
  status: "success" | "failed" | "skipped";
  detail: string;
  data?: Record<string, unknown>;
};

/**
 * One submitted `.eml` and what the pipeline concluded about it.
 *
 * `status` is the overall verdict; the per-stage statuses are why. A policy
 * rejection is `rejected_policy`, not `failed`: the pipeline worked and refused
 * the message, and the two must not be shown with the same word.
 */
export type IntakeFileResult = {
  filename: string;
  status: "processed" | "rejected_policy" | "duplicate" | "failed";
  stages: readonly IntakeStage[];
  byteSize?: number;
  sourceSha256?: string;
  messageId?: string;
  subject?: string;
  sender?: string;
  recipient?: string;
  date?: string;
  bodyPreview?: string;
  attachmentCount?: number;
  receivedCount?: number;
  actor?: string;
  labels?: readonly string[];
  confidence?: number;
  classificationScopeWarning?: string;
  policy?: {
    allowed: boolean | null;
    quarantine: boolean | null;
    reason: string;
  };
  provenance?: {
    complete: boolean | null;
    humanReviewRequired: boolean | null;
  };
  /** Present when the message became case evidence. */
  evidenceId?: string;
  reason?: string;
};

export type EmailIntakeResult = {
  caseId: string;
  files: readonly IntakeFileResult[];
  summary: {
    processed: number;
    rejectedPolicy: number;
    duplicate: number;
    failed: number;
  };
};

export interface AdminMember {
  id: string;
  name: string;
  email: string;
  role: SessionUser["role"];
  status: "active" | "invited" | "suspended";
  caseIds: readonly string[];
  credentialFingerprint?: string;
}

export interface InviteMemberInput {
  email: string;
  role: SessionUser["role"];
  caseIds: string[];
  credential?: string;
}

export function createAdapter(config: AdapterConfig) {
  const sessionCases: CaseRow[] = [
    {
      id: fixture.case.id,
      key: fixture.case.key,
      title: fixture.case.title,
      status: "open",
      ownerId: fixture.case.ownerId,
      evidenceCount: fixture.evidence.length,
      holdCount: fixture.case.holdCount,
      lastActivity: fixture.case.lastActivity,
      timezone: fixture.case.timezone,
    },
  ];
  const sessionCaseDetails = new Map<string, CaseSummary>();
  const sessionMembers: AdminMember[] = fixture.members.map((member) => ({
    ...member,
    email: member.email,
    caseIds: [...member.caseIds],
  }));
  const sessionAudit: AuditEntry[] = [];
  let sequence = 0;
  // Per-adapter set of removed ids, so `list` and `get` stay consistent
  // in mock mode and never leak across adapter instances.
  const sessionRemovedIds = new Set<string>();
  const requestJson = <T>(path: string, init?: RequestInit) => {
    if (!config.backend) {
      return Promise.resolve(failure("BACKEND_UNREACHABLE"));
    }
    return request<T>(config.backend.baseUrl, path, init);
  };

  return {
    session: {
      get: (): Promise<AdapterResult<SessionUser>> => {
        if (!config.backend) {
          return Promise.resolve(success<SessionUser>(fixture.session));
        }
        return requestJson<SessionUser>("/session");
      },
    },
    members: {
      list() {
        if (config.backend) {
          return requestJson<readonly AdminMember[]>("/admin/members");
        }
        return Promise.resolve(
          success<readonly AdminMember[]>(sessionMembers.map((member) => ({
            ...member,
            caseIds: [...member.caseIds],
          }))),
        );
      },
      async invite(input: InviteMemberInput): Promise<AdapterResult<AdminMember>> {
        if (config.backend) {
          return requestJson<AdminMember>("/admin/members/invitations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(input),
          });
        }
        const email = input.email.trim().toLocaleLowerCase();
        if (sessionMembers.some((member) => member.email.toLocaleLowerCase() === email)) {
          return failure("MEMBER_ALREADY_EXISTS");
        }
        const member: AdminMember = {
          id: `M-${sessionMembers.length + 1}`,
          name: email.split("@")[0],
          email,
          role: input.role,
          status: "invited",
          caseIds: [...input.caseIds],
          credentialFingerprint: "pending",
        };
        sessionMembers.push(member);
        return success({ ...member, caseIds: [...member.caseIds] });
      },
      async changeRole(
        memberId: string,
        role: SessionUser["role"],
        reason: string,
      ): Promise<AdapterResult<AdminMember>> {
        if (config.backend) {
          return requestJson<AdminMember>(
            `/admin/members/${encodeURIComponent(memberId)}/role`,
            {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ role, reason }),
            },
          );
        }
        const member = sessionMembers.find((candidate) => candidate.id === memberId);
        if (!member) return failure("NOT_FOUND");
        const previousRole = member.role;
        if (previousRole === role) return failure("ROLE_UNCHANGED");
        member.role = role;
        sessionAudit.push({
          id: `A-ROLE-${sessionAudit.length + 1}`,
          event: "member_role_changed",
          evidenceId: null,
          chain: "linked",
          memberId,
          actor: fixture.session.name,
          previousRole,
          role,
          reason: reason.trim(),
          at: new Date().toISOString(),
        });
        return success({ ...member, caseIds: [...member.caseIds] });
      },
    },
    cases: {
      list() {
        if (config.backend) {
          return requestJson<readonly CaseRow[]>("/cases");
        }
        return Promise.resolve(success<readonly CaseRow[]>([...sessionCases]));
      },
      get(id: string): Promise<AdapterResult<CaseSummary>> {
        if (config.backend) {
          return requestJson<CaseSummary>(
            `/cases/${encodeURIComponent(id)}`,
          );
        }
        if (id === fixture.case.id || id === fixture.case.key) {
          return Promise.resolve(success<CaseSummary>(fixture.case));
        }
        const created = sessionCaseDetails.get(id);
        return Promise.resolve(created ? success(created) : failure("NOT_FOUND"));
      },
      /**
       * Submit `.eml` files to the case's intake pipeline.
       *
       * One request for the whole batch: the server runs each file
       * independently and reports each outcome, so a batch is one action from
       * the reader's side and five verdicts from the pipeline's.
       */
      async emailIntake(
        caseId: string,
        files: readonly { name: string; bytes: ArrayBuffer }[],
      ): Promise<AdapterResult<EmailIntakeResult>> {
        if (!config.backend) {
          return Promise.resolve(failure("FEATURE_UNAVAILABLE"));
        }
        try {
          const form = new FormData();
          for (const file of files) {
            form.append(
              "files",
              new Blob([file.bytes], { type: "message/rfc822" }),
              file.name,
            );
          }
          const response = await fetch(
            `${config.backend.baseUrl}/cases/${encodeURIComponent(caseId)}/intake/email`,
            { method: "POST", body: form },
          );
          if (!response.ok) {
            const payload = (await response.json().catch(() => ({}))) as {
              error?: unknown;
            };
            return failure(namedError(payload.error, `HTTP_${response.status}`));
          }
          const body = (await response.json()) as EmailIntakeResult;
          return success(body);
        } catch {
          return failure("BACKEND_UNREACHABLE");
        }
      },

      async update(caseId: string, body: { status?: string }): Promise<AdapterResult<CaseSummary>> {
        if (config.backend) {
          return requestJson<CaseSummary>(
            `/cases/${encodeURIComponent(caseId)}`,
            {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            },
          );
        }
        const c = sessionCaseDetails.get(caseId);
        if (!c) return failure("NOT_FOUND");
        if (body.status) c.status = body.status as any;
        return Promise.resolve(success(c));
      },

      async create(input: CreateCaseInput): Promise<CreateCaseResult> {
        if (config.backend) {
          const result = await requestJson<{ id: string; key: string }>("/cases", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(input),
          });
          if (result.ok) {
            return {
              ok: true,
              value: { id: result.value.id, key: result.value.key },
            };
          }
          return {
            ok: false,
            error:
              result.error === "CASE_KEY_TAKEN" || result.error === "HTTP_409"
                ? "CASE_KEY_TAKEN"
                : "BACKEND_UNREACHABLE",
          };
        }
        if (sessionCases.some((row) => row.key === input.key)) {
          return { ok: false, error: "CASE_KEY_TAKEN" };
        }
        sequence += 1;
        const id = `case-${Date.now().toString(36)}-${sequence}`;
        sessionCases.push({
          id,
          key: input.key,
          title: input.title,
          status: "open",
          ownerId: fixture.case.ownerId,
          evidenceCount: 0,
          holdCount: 0,
          lastActivity: new Date().toISOString(),
          timezone: input.timezone,
        });
        const summary: CaseSummary = {
          ...fixture.case,
          id,
          key: input.key,
          title: input.title,
          jurisdiction: input.jurisdiction,
          timezone: input.timezone,
          status: "open",
          holdCount: 0,
          integrityStatus: "clear",
        };
        sessionCaseDetails.set(id, summary);
        sessionCaseDetails.set(input.key, summary);
        return { ok: true, value: { id, key: input.key } };
      },
    },
    evidence: {
      list(caseId: string, filters?: EvidenceFilters) {
        if (config.backend) {
          const params = new URLSearchParams();
          if (filters?.status) params.set("status", filters.status);
          if (filters?.category) params.set("category", filters.category);
          if (filters?.source) params.set("source", filters.source);
          if (filters?.documentType) params.set("document_type", filters.documentType);
          if (filters?.author) params.set("author", filters.author);
          if (filters?.date) params.set("date", filters.date);
          const qs = params.toString();
          return requestJson<readonly Evidence[]>(
            `/cases/${encodeURIComponent(caseId)}/evidence${qs ? `?${qs}` : ""}`,
          );
        }
        if (caseId !== fixture.case.id) {
          return Promise.resolve(failure("NOT_FOUND"));
        }
        const all: readonly Evidence[] = [
          ...(fixture.evidence as readonly Evidence[]).filter(
            (row) => !sessionRemovedIds.has(row.id),
          ),
          ...sessionEvidence.filter((row) => !sessionRemovedIds.has(row.id)),
        ];
        const matched = all.filter((row) => {
          if (filters?.status === "hold" && row.status !== "integrity_hold") return false;
          if (filters?.status && filters.status !== "hold" && row.status !== filters.status) return false;
          if (filters?.category && row.category !== filters.category) return false;
          if (filters?.source && row.source !== filters.source) return false;
          if (filters?.documentType) {
            if (row.analysis?.documentType !== filters.documentType) return false;
          }
          if (filters?.author) {
            const a = row.analysis?.metadata?.author;
            if (!a || !a.toLowerCase().includes(filters.author.toLowerCase())) {
              return false;
            }
          }
          if (filters?.date) {
            if (row.analysis?.metadata?.date !== filters.date) return false;
          }
          return true;
        });
        return Promise.resolve(success(matched));
      },
      async ingest(caseId: string, input: IngestInput): Promise<IngestResult> {
        if (config.backend) {
          try {
            const form = new FormData();
            form.append("file", new Blob([input.bytes], { type: input.type }), input.name);
            if (input.category) form.append("category", input.category);
            if (input.source) form.append("source", input.source);
            const response = await fetch(
              `${config.backend.baseUrl}/cases/${encodeURIComponent(caseId)}/evidence`,
              { method: "POST", body: form },
            );
            if (!response.ok) {
              const err = (await response.json().catch(() => ({}))) as {
                error?: unknown;
                failedStage?: "received" | "preserved" | "scanned" | "indexed";
              };
              return {
                ok: false,
                error: namedError(err.error, `HTTP_${response.status}`),
                failedStage: err.failedStage,
              };
            }
            const body = (await response.json()) as {
              id: string;
              hash: string;
              sourceSha256?: string;
              duplicate?: boolean;
              processingStatus?: ExtractStatus;
              analysis?: EvidenceAnalysis | null;
              category?: string | null;
              source?: string | null;
            };
            return {
              ok: true,
              value: {
                id: body.id,
                hash: body.hash,
                // The artifact hash the server bound to the record. Reported
                // separately from `hash` so a reader can see they are the same
                // value the pipeline stores as `source_sha256`.
                sourceSha256: body.sourceSha256 ?? body.hash,
                duplicate: Boolean(body.duplicate),
                processingStatus: body.processingStatus,
                analysis: body.analysis ?? null,
                category: body.category ?? null,
                source: body.source ?? null,
              },
            };
          } catch {
            return { ok: false, error: "BACKEND_UNREACHABLE" };
          }
        }
        if (caseId !== fixture.case.id) return { ok: false, error: "NOT_FOUND" };
        const hash = await sha256Hex(input.bytes);
        const duplicate = sessionEvidence.some((e) => e.hash === hash);
        const id = `E-${1048 + sessionEvidence.length}`;
        sessionEvidence.push({
          id,
          name: input.name,
          // Offline mode stores the bytes and reads nothing, so "stored" is the
          // truthful status. "indexed" claimed a step that never ran here.
          status: "stored",
          badges: ["received", "stored"],
          quarantinedReason: null,
          holdReason: null,
          duplicateCandidate: duplicate,
          hash,
          category: input.category ?? null,
          source: input.source ?? null,
        });
        return {
          ok: true,
          value: {
            id,
            hash,
            sourceSha256: hash,
            duplicate,
            processingStatus: "stored",
            analysis: null,
            category: input.category ?? null,
            source: input.source ?? null,
          },
        };
      },
      get(id: string) {
        if (config.backend) {
          return requestJson<Evidence>(`/evidence/${encodeURIComponent(id)}`);
        }
        if (sessionRemovedIds.has(id)) {
          return Promise.resolve(failure("NOT_FOUND"));
        }
        const evidence = [...fixture.evidence, ...sessionEvidence].find(
          (item) => item.id === id,
        );
        return Promise.resolve(evidence ? success(evidence) : failure("NOT_FOUND"));
      },
      async remove(
        id: string,
      ): Promise<AdapterResult<{ id: string; removed: true }>> {
        if (config.backend) {
          return request<{ id: string; removed: true }>(
            config.backend.baseUrl,
            `/evidence/${encodeURIComponent(id)}`,
            { method: "DELETE" },
          );
        }
        if (sessionRemovedIds.has(id)) {
          return failure("NOT_FOUND");
        }
        const inFixture = fixture.evidence.some((e) => e.id === id);
        const inSession = sessionEvidence.some((e) => e.id === id);
        if (!inFixture && !inSession) {
          return failure("NOT_FOUND");
        }
        sessionRemovedIds.add(id);
        const idx = sessionEvidence.findIndex((e) => e.id === id);
        if (idx !== -1) sessionEvidence.splice(idx, 1);
        return success({ id, removed: true as const });
      },
      originalUrl(id: string): string | null {
        return config.backend
          ? `${config.backend.baseUrl.replace(/\/$/, "")}/evidence/${encodeURIComponent(id)}/download`
          : null;
      },
      text(id: string) {
        if (config.backend) {
          return requestJson<EvidenceText>(
            `/evidence/${encodeURIComponent(id)}/text`,
          );
        }
        return Promise.resolve(failure("FEATURE_UNAVAILABLE"));
      },
      custody(id: string) {
        if (config.backend) {
          return requestJson<readonly CustodyEntry[]>(
            `/evidence/${encodeURIComponent(id)}/custody`,
          );
        }
        const entries = (fixture.custody as Record<string, readonly CustodyEntry[]>)[id];
        if (entries) return Promise.resolve(success(entries));
        const exists = [...fixture.evidence, ...sessionEvidence].some((e) => e.id === id);
        return Promise.resolve(exists ? success([]) : failure("NOT_FOUND"));
      },
      async verifyDoctrine(id: string): Promise<AdapterResult<{ match: boolean; reason: string | null }>> {
        if (config.backend) {
          return requestJson<{ match: boolean; reason: string | null }>(
            `/evidence/${encodeURIComponent(id)}/verify-doctrine`,
            { method: "POST" },
          );
        }
        return failure("FEATURE_UNAVAILABLE");
      },

      verify(id: string) {
        if (config.backend) {
          return requestJson<Verification>(
            `/evidence/${encodeURIComponent(id)}/verify`,
            { method: "POST" },
          );
        }
        const verification =
          fixture.verification[id as keyof typeof fixture.verification];
        return Promise.resolve(
          verification ? success(verification) : failure("NOT_FOUND"),
        );
      },

      summarize(id: string) {
        if (config.backend) {
          return requestJson<SummaryResult>(
            `/evidence/${encodeURIComponent(id)}/summarize`,
            { method: "POST" },
          );
        }
        return Promise.resolve(failure("FEATURE_UNAVAILABLE"));
      },

      /**
       * The summary already stored for this item.
       *
       * Separate from `summarize` on purpose: opening the drawer again must not
       * cost another model call, and a reader revisiting a summary is entitled
       * to the one that is on record rather than a fresh, slightly different
       * one.
       */
      summary(id: string) {
        if (config.backend) {
          return requestJson<SummaryResult>(
            `/evidence/${encodeURIComponent(id)}/summarize`,
          );
        }
        return Promise.resolve(failure("FEATURE_UNAVAILABLE"));
      },

      async consult(id: string): Promise<AdapterResult<{ id: string; consultation: Consultation | null }>> {
        if (config.backend) {
          return requestJson<{ id: string; consultation: Consultation | null }>(
            `/evidence/${encodeURIComponent(id)}/consult`,
            { method: "POST" },
          );
        }
        return failure("FEATURE_UNAVAILABLE");
      },
    },
    exports: {
      async generate(
        caseId: string,
        opts?: { includeSummary?: boolean; format?: "zip" | "pdf" },
      ): Promise<AdapterResult<{ blob: Blob; filename: string }>> {
        if (config.backend) {
          try {
            const params = new URLSearchParams();
            if (opts?.includeSummary === false) params.set("include_summary", "false");
            if (opts?.format === "pdf") params.set("format", "pdf");
            const qs = params.toString();
            const res = await fetch(
              `${config.backend.baseUrl}/cases/${encodeURIComponent(caseId)}/export${qs ? "?" + qs : ""}`,
              { method: "POST" },
            );
            if (!res.ok) return failure(`HTTP_${res.status}`);
            const blob = await res.blob();
            const disposition = res.headers.get("Content-Disposition") || "";
            const match = disposition.match(/filename="([^"]+)"/);
            const fallback =
              opts?.format === "pdf" ? `case_${caseId}_report.pdf` : `case_${caseId}_export.zip`;
            const filename = match ? match[1] : fallback;
            return success({ blob, filename });
          } catch {
            return failure("BACKEND_UNREACHABLE");
          }
        }
        return failure("FEATURE_UNAVAILABLE");
      },

      preview(caseId: string, type: string) {
        if (config.backend) {
          return requestJson<ExportPreview>(
            `/cases/${encodeURIComponent(caseId)}/exports/preview?type=${encodeURIComponent(type)}`,
            { method: "POST" },
          );
        }
        return caseId === fixture.case.id
          ? Promise.resolve(
              success({
                type,
                gates: fixture.exportGates,
                blocked: fixture.exportGates.some((gate) => gate.result === "fail"),
              }),
            )
          : Promise.resolve(failure("NOT_FOUND"));
      },
    },
    anchoring: {
      /**
       * The case's published anchor, or the reason there is none.
       *
       * Answered offline too, because "this build has no zone configured" is a
       * truthful state the reader can act on — unlike a proof, which cannot be
       * computed here without inventing a claim about their case.
       */
      get(caseId: string) {
        if (config.backend) {
          return requestJson<AnchorState>(
            `/cases/${encodeURIComponent(caseId)}/anchor`,
          );
        }
        return Promise.resolve(
          success<AnchorState>({
            anchored: false,
            configured: false,
            expectedName: `case-${caseId}.chain.creovate.digital`,
          }),
        );
      },
      publish(caseId: string) {
        if (config.backend) {
          return requestJson<AnchorState>(
            `/cases/${encodeURIComponent(caseId)}/anchor`,
            { method: "POST" },
          );
        }
        return Promise.resolve(failure("FEATURE_UNAVAILABLE"));
      },
    },
    audit: {
      list(caseId: string) {
        if (config.backend) {
          return requestJson<readonly AuditEntry[]>(
            `/cases/${encodeURIComponent(caseId)}/audit`,
          );
        }
        return Promise.resolve(
          caseId === fixture.case.id
            ? success<readonly AuditEntry[]>([...fixture.audit, ...sessionAudit])
            : success<readonly AuditEntry[]>([]),
        );
      },
      /**
       * Re-derive every cryptographic claim the case makes.
       *
       * POST, and never answered offline: a proof computed from the sample
       * fixture would be a proof about the sample, presented as if it were
       * about the reader's case. There is no honest offline answer.
       */
      verifyProofs(caseId: string) {
        if (config.backend) {
          return requestJson<ProofsReport>(
            `/cases/${encodeURIComponent(caseId)}/audit/verify-proofs`,
            { method: "POST" },
          );
        }
        return Promise.resolve(failure("FEATURE_UNAVAILABLE"));
      },
    },
    timeline: {
      list(caseId: string) {
        if (config.backend) {
          return requestJson<readonly TimelineEvent[]>(
            `/cases/${encodeURIComponent(caseId)}/timeline`,
          );
        }
        return Promise.resolve(
          caseId === fixture.case.id
            ? success<readonly TimelineEvent[]>(fixture.timeline)
            : failure("NOT_FOUND"),
        );
      },
    },
    search: {
      query(caseId: string, query: string) {
        if (config.backend) {
          return requestJson<readonly SearchResult[]>(
            `/cases/${encodeURIComponent(caseId)}/search?q=${encodeURIComponent(query)}`,
          );
        }
        if (caseId !== fixture.case.id) {
          return Promise.resolve(failure("NOT_FOUND"));
        }
        if (config.searchIndexReady === false) {
          return Promise.resolve(failure("INDEX_BUILDING"));
        }
        const needle = query.trim().toLocaleLowerCase();
        return Promise.resolve(
          success(
            fixture.searchResults.filter((result) =>
              `${result.id} ${result.excerpt}`.toLocaleLowerCase().includes(needle),
            ),
          ),
        );
      },
    },
  };
}
