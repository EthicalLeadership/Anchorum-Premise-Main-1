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
};
export interface IngestInput {
  name: string;
  size: number;
  type: string;
  bytes: ArrayBuffer;
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
type ExportPreview = {
  type: string;
  gates: typeof fixture.exportGates;
  blocked: boolean;
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
type SearchResult = (typeof fixture.searchResults)[number];
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

export interface AdminMember {
  id: string;
  name: string;
  email: string;
  role: SessionUser["role"];
  status: "active" | "invited" | "suspended";
  caseIds: readonly string[];
}

export interface InviteMemberInput {
  email: string;
  role: SessionUser["role"];
  caseIds: string[];
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
      list(caseId: string) {
        if (config.backend) {
          return requestJson<readonly Evidence[]>(
            `/cases/${encodeURIComponent(caseId)}/evidence`,
          );
        }
        return caseId === fixture.case.id
          ? Promise.resolve(
              success<readonly Evidence[]>([
                ...(fixture.evidence as readonly Evidence[]),
                ...sessionEvidence,
              ]),
            )
          : Promise.resolve(failure("NOT_FOUND"));
      },
      async ingest(caseId: string, input: IngestInput): Promise<IngestResult> {
        if (config.backend) {
          try {
            const form = new FormData();
            form.append("file", new Blob([input.bytes], { type: input.type }), input.name);
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
          },
        };
      },
      get(id: string) {
        if (config.backend) {
          return requestJson<Evidence>(`/evidence/${encodeURIComponent(id)}`);
        }
        const evidence = [...fixture.evidence, ...sessionEvidence].find(
          (item) => item.id === id,
        );
        return Promise.resolve(evidence ? success(evidence) : failure("NOT_FOUND"));
      },
      originalUrl(id: string): string | null {
        return config.backend
          ? `${config.backend.baseUrl.replace(/\/$/, "")}/evidence/${encodeURIComponent(id)}/download`
          : null;
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
    },
    exports: {
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
