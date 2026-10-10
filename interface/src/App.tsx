import { AppShell } from "./components/AppShell";
import { translate } from "./i18n";
import type { ShellBootstrap } from "./types";

const routes: ShellBootstrap["routes"] = {
  cases: "/cases",
  signIn: "/auth/login",
  signOut: "/auth/signout",
  administration: "/admin",
  globalSection: (section) => {
    const paths = {
      workspace: "/workspace",
      cases: "/cases",
      evidence: "/evidence",
      missions: "/missions",
      "legal-lens": "/legal-lens",
      admin: "/admin",
    };
    return paths[section];
  },
  caseSection: (caseId, section) =>
    `/cases/${encodeURIComponent(caseId)}/${section}`,
  evidenceHolds: (caseId) =>
    `/cases/${encodeURIComponent(caseId)}/evidence?filter=hold`,
};

export function App() {
  const locale =
    new URLSearchParams(window.location.search).get("lang") === "fr"
      ? "fr"
      : "en";

  return (
    <AppShell
      locale={locale}
      user={null}
      case={null}
      activeGlobalSection="workspace"
      activeSection="overview"
      permissions={{
        canSeeSection: () => false,
        canSeeGlobalSection: () => false,
      }}
      routes={routes}
    >
      <section className="empty-state" aria-labelledby="empty-state-title">
        <h1 id="empty-state-title">
          {translate(locale, "topbar.switch_case.none")}
        </h1>
        <p>{translate(locale, "state.no_case_body")}</p>
        <a className="btn btn--primary" href={routes.cases}>
          {translate(locale, "case.list.browse")}
        </a>
      </section>
    </AppShell>
  );
}
