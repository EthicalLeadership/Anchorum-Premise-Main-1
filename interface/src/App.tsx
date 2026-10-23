import { AppShell } from "./components/AppShell";
import { useEffect, useMemo, useState } from "react";
import { createAdapter } from "./adapter";
import { CaseList } from "./screens/CaseList";
import { Overview } from "./screens/Overview";
import { EvidenceIntake } from "./screens/EvidenceIntake";
import { Search } from "./screens/Search";
import { Register } from "./screens/Register";
import { EvidenceViewer } from "./screens/EvidenceViewer";
import { CreateCase } from "./screens/CreateCase";
import { Timeline } from "./screens/Timeline";
import { Administration } from "./screens/Administration";
import { AuditExports } from "./screens/AuditExports";
import { translate } from "./i18n";
import { StateBlock } from "./components/StateBlock";
import type { CaseSection, CaseSummary, SessionUser, ShellBootstrap } from "./types";

const routes: ShellBootstrap["routes"] = {
  cases: "#/cases",
  signIn: "/auth/login",
  signOut: "/auth/signout",
  administration: "#/admin",
  globalSection: (section) => {
    const paths = {
      workspace: "#/workspace",
      cases: "#/cases",
      evidence: "#/evidence",
      missions: "#/missions",
      "legal-lens": "#/legal-lens",
      admin: "#/admin",
    };
    return paths[section];
  },
  caseSection: (caseId, section) =>
    `#/cases/${encodeURIComponent(caseId)}/${section}`,
  evidenceHolds: (caseId) =>
    `#/cases/${encodeURIComponent(caseId)}/evidence?filter=hold`,
};

export function App() {
  const locale =
    new URLSearchParams(window.location.search).get("lang") === "fr"
      ? "fr"
      : "en";

  const backendBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();
  const adapter = useMemo(
    () =>
      createAdapter({
        backend: backendBaseUrl ? { baseUrl: backendBaseUrl } : null,
      }),
    [backendBaseUrl],
  );
  const [session, setSession] = useState<SessionUser | null>(null);
  const [sessionError, setSessionError] = useState(false);
  useEffect(() => {
    let live = true;
    adapter.session.get().then((r) => {
      if (!live) return;
      if (r.ok) setSession(r.value);
      else setSessionError(true);
    });
    return () => {
      live = false;
    };
  }, [adapter]);
  const [hash, setHash] = useState(window.location.hash);
  const path = hash.split("?")[0];
  const caseRoute = path.match(/^#\/cases\/([^/]+)(?:\/|$)/);
  const activeCaseId =
    caseRoute && caseRoute[1] !== "new"
      ? decodeURIComponent(caseRoute[1])
      : null;
  const [caseLoad, setCaseLoad] = useState<
    | { caseId: string; kind: "loading" }
    | { caseId: string; kind: "ready"; value: CaseSummary | null }
    | null
  >(null);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  useEffect(() => {
    if (!activeCaseId) {
      setCaseLoad(null);
      return;
    }
    let live = true;
    setCaseLoad({ caseId: activeCaseId, kind: "loading" });
    adapter.cases.get(activeCaseId).then((result) => {
      if (!live) return;
      setCaseLoad({
        caseId: activeCaseId,
        kind: "ready",
        value: result.ok ? result.value : null,
      });
    });
    return () => {
      live = false;
    };
  }, [adapter, activeCaseId]);

  // Remember the last opened case so the workspace home screen can surface
  // a Continue banner. Reads caseLoad (a state value) rather than the
  // derived activeCase, because hooks must run before early returns.
  useEffect(() => {
    if (caseLoad?.kind === "ready" && caseLoad.value) {
      localStorage.setItem("anchorum:lastCaseId", caseLoad.value.id);
      localStorage.setItem("anchorum:lastCaseAt", new Date().toISOString());
    }
  }, [caseLoad]);

  if (sessionError) return <StateBlock locale={locale} kind="error" />;
  if (!session) return <StateBlock locale={locale} kind="loading" />;
  if (
    activeCaseId &&
    (caseLoad?.caseId !== activeCaseId || caseLoad.kind === "loading")
  ) {
    return <StateBlock locale={locale} kind="loading" />;
  }
  if (activeCaseId && caseLoad?.kind === "ready" && !caseLoad.value) {
    return (
      <StateBlock
        locale={locale}
        kind="error"
        message={translate(locale, "error.not_found")}
        action={{
          label: translate(locale, "case.list.browse"),
          href: "#/cases",
        }}
      />
    );
  }
  const activeCase =
    activeCaseId && caseLoad?.caseId === activeCaseId && caseLoad.kind === "ready"
      ? caseLoad.value
      : null;


  const activeSection = path.endsWith("/timeline")
    ? "timeline"
    : path.endsWith("/audit")
      ? "audit"
      : path.endsWith("/settings")
        ? "settings"
        : path.includes("/evidence") || path.endsWith("/register")
          ? "evidence"
          : "overview";
  const activeGlobalSection: ShellBootstrap["activeGlobalSection"] =
    path === "#/admin" ? "admin" : "workspace";

  return (
    <AppShell
      locale={locale}
      session={session}
      case={activeCase}
      activeGlobalSection={activeGlobalSection}
      activeSection={activeSection}
      permissions={{
        canSeeSection: (section: CaseSection) =>
          session.role === "case_admin" ||
          (session.role === "reviewer" && section !== "settings") ||
          (session.role === "auditor" &&
            (section === "overview" ||
              section === "evidence" ||
              section === "audit")),
        canSeeGlobalSection: (s) => s === "cases" || (s === "admin" && session.role === "case_admin"),
      }}
      routes={routes}
    >
      {path === "#/cases" ? (
        <CaseList locale={locale} adapter={adapter} />
      ) : path === "#/cases/new" ? (
        <CreateCase locale={locale} adapter={adapter} />
      ) : /^#\/cases\/[^/]+(?:\/overview)?$/.test(path) ? (
        <Overview
          locale={locale}
          adapter={adapter}
          caseId={decodeURIComponent(path.split("/")[2])}
        />
      ) : /^#\/cases\/[^/]+\/intake$/.test(path) ? (
        <EvidenceIntake
          locale={locale}
          adapter={adapter}
          caseId={decodeURIComponent(hash.split("/")[2])}
        />
      ) : /^#\/cases\/[^/]+\/(evidence|register)$/.test(path) ? (
        <Register
          locale={locale}
          adapter={adapter}
          caseId={decodeURIComponent(hash.split("/")[2])}
        />
      ) : /^#\/cases\/[^/]+\/search$/.test(path) ? (
        <Search
          locale={locale}
          adapter={adapter}
          caseId={decodeURIComponent(hash.split("/")[2])}
        />
      ) : /^#\/cases\/[^/]+\/timeline$/.test(path) ? (
        <Timeline
          locale={locale}
          adapter={adapter}
          caseId={decodeURIComponent(hash.split("/")[2])}
        />
      ) : /^#\/cases\/[^/]+\/audit$/.test(path) ? (
        <AuditExports
          locale={locale}
          adapter={adapter}
          caseId={decodeURIComponent(hash.split("/")[2])}
        />
      ) : /^#\/cases\/[^/]+\/evidence\/[^/]+$/.test(path) ? (
        // Parsed from `path`, not `hash`: a search hit links here with
        // `?at=<offset>`, and splitting the raw hash made the evidence id
        // "E-…?at=480", which 404s.
        <EvidenceViewer
          locale={locale}
          adapter={adapter}
          caseId={decodeURIComponent(path.split("/")[2])}
          evidenceId={decodeURIComponent(path.split("/")[4])}
        />
      ) : path === "#/admin" ? (
        session.role === "case_admin" ? (
          <Administration locale={locale} adapter={adapter} />
        ) : (
          <StateBlock
            locale={locale}
            kind="permission_limited"
            message={translate(locale, "state.permission_limited")}
          />
        )
      ) : path === "#/workspace" || path === "" || path === "#" ? (
        <CaseList locale={locale} adapter={adapter} />
      ) : (
      <section className="empty-state" aria-labelledby="empty-state-title">
        <h1 id="empty-state-title">
          {translate(locale, "topbar.switch_case.none")}
        </h1>
        <p>{translate(locale, "state.no_case_body")}</p>
        <a className="btn btn--primary" href="#/cases">
          {translate(locale, "case.list.browse")}
        </a>
      </section>
      )}
    </AppShell>
  );
}
