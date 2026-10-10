export type Locale = "en" | "fr";

export type CaseSection =
  | "overview"
  | "evidence"
  | "timeline"
  | "audit"
  | "settings";

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
