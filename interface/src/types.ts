export type Locale = "en" | "fr";

export type CaseSection =
  | "overview"
  | "evidence"
  | "intake"
  | "timeline"
  | "audit"
  | "settings"
  | "warroom";

export type WorkspaceSection =
  | "workspace"
  | "cases"
  | "evidence"
  | "missions"
  | "legal-lens"
  | "admin";

export type SessionRole = "case_admin" | "reviewer" | "auditor";

export interface SessionUser {
  name: string;
  role: SessionRole;
}

export interface CaseSummary {
  id: string;
  key: string;
  title: string;
  jurisdiction: string;
  timezone: string;
  status: "open" | "closed" | "on_hold";
  holdCount: number;
  integrityStatus: "clear" | "hold" | "unknown" | "verifying";
}

export interface CustodyEntry {
  id: string;
  actor: string;
  action: "uploaded" | "preserved" | "opened" | "downloaded" | "verified" | "redacted";
  at: string;
  chain: "linked" | "broken" | "not_checked";
}

export interface DrawerObject {
  id: string;
  custody: CustodyEntry[];
  parent: string | null;
  source: string;
  parserVersion: string;
  verification: {
    outcome: "pass" | "fail" | "pending" | "unavailable";
    failingStep?: string | null;
  };
  corrections: Array<{
    id: string;
    extractedValue: string;
    reason: string;
    at: string;
  }>;
}

export interface ShellPermissions {
  canSeeSection: (section: CaseSection) => boolean;
  canSeeGlobalSection: (section: WorkspaceSection) => boolean;
}

export interface ShellRoutes {
  cases: string;
  signIn: string;
  signOut: string;
  administration: string;
  globalSection: (section: WorkspaceSection) => string;
  caseSection: (caseId: string, section: CaseSection) => string;
  evidenceHolds: (caseId: string) => string;
}

export interface ShellBootstrap {
  locale: Locale;
  session: SessionUser;
  case: CaseSummary | null;
  activeGlobalSection: WorkspaceSection;
  activeSection: CaseSection;
  permissions: ShellPermissions;
  routes: ShellRoutes;
}

export interface ChronologyEntry {
  message_id: string;
  date?: string | null;
  date_raw?: string | null;
  from_address?: string | null;
  to_address?: string | null;
  subject?: string | null;
}

export interface CommEdge {
  from_address: string;
  to_address: string;
  count: number;
}

export interface GapItem {
  id: string;
  status: string;
  description: string;
}

export interface Finding {
  id: string;
  rule: string;
  title: string;
  triggering_message_id: string;
  evidence_message_ids: string[];
  rationale: string;
  status: "candidate" | "confirmed" | "dismissed";
}

/**
 * The full analysis record served by GET /evidence/{id}/analysis.
 * Distinct from EvidenceAnalysis (the compact counts-only view on each item).
 */
export type AnalysisScopeRecord = {
  scope: string;
  chars: number;
  conceptId: string | null;
  classification: string;
  admissible: boolean;
  matchedConcepts: string[];
  fallbackReason: string | null;
};

export type AnalysisCoverage = {
  scopesTotal: number;
  scopesMatched: number;
  scopesFallback: number;
  scopesInsufficient: number;
  ratio: number;
  warning: string | null;
};

export type AnalysisExtract = { status: string; chars: number; sha256: string; error: string };
export type AnalysisProjection = { engineVersion: string; lexiconHash: string; configHash: string };
export type AnalysisSource = { sha256: string; bytes: number; mediaType: string; filename: string };

export type AnalysisRecord = {
  id: string;
  status: string;
  reason: string;
  source: AnalysisSource;
  extract: AnalysisExtract;
  projection: AnalysisProjection;
  coverage: AnalysisCoverage;
  scopes: AnalysisScopeRecord[];
};
