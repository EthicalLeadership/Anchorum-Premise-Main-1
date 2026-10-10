import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";
import {
  formatDateTime,
  translate,
  type MessageKey,
  type MessageParameters,
} from "../i18n";
import type {
  CaseSection,
  CustodyEntry,
  DrawerObject,
  Locale,
  SessionRole,
  ShellBootstrap,
  WorkspaceSection,
} from "../types";

interface AppShellProps extends ShellBootstrap {
  children:
    | ReactNode
    | ((
        actions: {
          openDrawer: (item: DrawerObject, trigger?: HTMLElement) => void;
        },
      ) => ReactNode);
  onVerify?: (item: DrawerObject) => Promise<void>;
}

const sections: CaseSection[] = [
  "overview",
  "evidence",
  "timeline",
  "audit",
  "settings",
];

const sectionLabels: Record<CaseSection, MessageKey> = {
  overview: "nav.overview",
  evidence: "nav.evidence",
  timeline: "nav.timeline",
  audit: "nav.audit",
  settings: "nav.settings",
};

const workspaceSections: WorkspaceSection[] = [
  "workspace",
  "cases",
  "evidence",
  "missions",
  "legal-lens",
];

const workspaceLabels: Record<WorkspaceSection, MessageKey> = {
  workspace: "nav.workspace",
  cases: "nav.cases",
  evidence: "nav.evidence",
  missions: "nav.missions",
  "legal-lens": "nav.legal_lens",
  admin: "nav.admin",
};

const verificationLabels: Record<
  DrawerObject["verification"]["outcome"],
  MessageKey
> = {
  pass: "verification.pass",
  fail: "verification.fail",
  pending: "verification.pending",
  unavailable: "verification.unavailable",
};

const chainLabels: Record<
  DrawerObject["custody"][number]["chain"],
  MessageKey
> = {
  linked: "chain.linked",
  broken: "chain.broken",
  not_checked: "chain.not_checked",
};

const custodyActionLabels: Record<CustodyEntry["action"], MessageKey> = {
  uploaded: "custody.uploaded",
  preserved: "custody.preserved",
  opened: "custody.opened",
  downloaded: "custody.downloaded",
  verified: "custody.verified",
  redacted: "custody.redacted",
};

const caseStatusLabels: Record<
  NonNullable<ShellBootstrap["case"]>["status"],
  MessageKey
> = {
  open: "case.header.status.open",
  closed: "case.header.status.closed",
  on_hold: "case.header.status.on_hold",
};

const RAIL_BY_ROLE: Record<SessionRole, readonly CaseSection[]> = {
  case_admin: ["overview", "evidence", "timeline", "audit", "settings"],
  reviewer: ["overview", "evidence", "timeline", "audit"],
  auditor: ["overview", "evidence", "audit"],
};

export function AppShell({
  locale,
  session,
  case: activeCase,
  activeGlobalSection,
  activeSection,
  permissions,
  routes,
  children,
  onVerify,
}: AppShellProps) {
  const [openMenu, setOpenMenu] = useState<"case" | "user" | null>(null);
  const [selectedItem, setSelectedItem] = useState<DrawerObject | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [verificationError, setVerificationError] = useState<string | null>(
    null,
  );
  const [verifying, setVerifying] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const drawerTriggerRef = useRef<HTMLElement | null>(null);
  const menuTriggerRef = useRef<HTMLButtonElement>(null);
  const t = (key: MessageKey, parameters?: MessageParameters) =>
    translate(locale, key, parameters);

  const closeDrawer = useCallback(() => {
    setDrawerOpen(false);
    setVerificationError(null);
  }, []);

  const openDrawer = useCallback(
    (item: DrawerObject, trigger?: HTMLElement) => {
      const activeElement = document.activeElement;
      drawerTriggerRef.current =
        trigger ??
        (activeElement instanceof HTMLElement ? activeElement : null);
      setSelectedItem(item);
      setVerificationError(null);
      setDrawerOpen(true);
    },
    [],
  );

  useEffect(() => {
    if (!drawerOpen) return;
    const firstControl = drawerRef.current?.querySelector<HTMLElement>(
      "button, a[href], input, select, textarea, [tabindex]:not([tabindex='-1'])",
    );
    firstControl?.focus();
  }, [drawerOpen, selectedItem]);

  useEffect(() => {
    if (drawerOpen || !drawerTriggerRef.current) return;
    const trigger = drawerTriggerRef.current;
    if (trigger.isConnected) {
      trigger.focus();
    } else {
      document.querySelector<HTMLElement>("#main")?.focus();
    }
    drawerTriggerRef.current = null;
  }, [drawerOpen]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (drawerOpen) {
        event.preventDefault();
        closeDrawer();
      } else if (openMenu) {
        event.preventDefault();
        setOpenMenu(null);
        menuTriggerRef.current?.focus();
      }
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (!target.closest("[data-menu-root]")) setOpenMenu(null);
    }

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [closeDrawer, drawerOpen, openMenu]);

  function toggleMenu(
    menu: "case" | "user",
    event: MouseEvent<HTMLButtonElement>,
  ) {
    menuTriggerRef.current = event.currentTarget;
    setOpenMenu((current) => (current === menu ? null : menu));
  }

  async function verifySelectedItem() {
    if (!selectedItem || !onVerify || verifying) return;
    setVerifying(true);
    setVerificationError(null);
    try {
      await onVerify(selectedItem);
    } catch {
      setVerificationError(t("verification.error"));
    } finally {
      setVerifying(false);
    }
  }

  const content =
    typeof children === "function" ? children({ openDrawer }) : children;

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        {t("a11y.skip_to_main")}
      </a>

      <header className="topbar">
        <div className="topbar__identity">
          <a className="topbar__wordmark" href={routes.globalSection("workspace")}>
            Anchorum
          </a>
          {activeCase && (
            <div className="menu-root" data-menu-root>
              <button
                type="button"
                className="topbar__switcher"
                aria-expanded={openMenu === "case"}
                aria-controls="case-menu"
                onClick={(event) => toggleMenu("case", event)}
              >
                <span className="mono">{activeCase.key}</span>
                <span>{activeCase.title}</span>
                <span aria-hidden="true">▾</span>
                <span className="sr-only">
                  {t("topbar.switch_case")}
                </span>
              </button>
              <div
                id="case-menu"
                className="menu"
                hidden={openMenu !== "case"}
              >
                <a href={routes.cases}>{t("case.list.browse")}</a>
              </div>
            </div>
          )}
        </div>

        {(
          <nav className="topbar__primary-nav" aria-label={t("nav.primary")}>
            {workspaceSections.map((section) => {
              if (!permissions.canSeeGlobalSection(section)) return null;
              if (section === "admin" && session.role !== "case_admin") return null;
              return (
                <a
                  key={section}
                  href={routes.globalSection(section)}
                  aria-current={
                    activeGlobalSection === section ? "page" : undefined
                  }
                >
                  {t(workspaceLabels[section])}
                </a>
              );
            })}
          </nav>
        )}

        <div className="topbar__utility">
          <div
            className="topbar__locale"
            role="group"
            aria-label={t("topbar.language")}
          >
            <LocaleLink locale={locale} target="fr" />
            <span aria-hidden="true">|</span>
            <LocaleLink locale={locale} target="en" />
          </div>

          {(
            <div className="menu-root" data-menu-root>
              <button
                type="button"
                className="topbar__user"
                aria-expanded={openMenu === "user"}
                aria-controls="user-menu"
                onClick={(event) => toggleMenu("user", event)}
              >
                <span>{session.name}</span>
                <span aria-hidden="true">▾</span>
                <span className="sr-only">
                  {t("topbar.user_menu")}
                </span>
              </button>
              <div
                id="user-menu"
                className="menu"
                hidden={openMenu !== "user"}
              >
                {session.role === "case_admin" && (
                  <a href={routes.administration}>
                    {t("topbar.user_menu.administration")}
                  </a>
                )}
                <a href={routes.signOut}>{t("topbar.sign_out")}</a>
              </div>
            </div>
          )}
        </div>
      </header>

      {activeCase && (
        <section className="case-header" aria-label={t("case.header_label")}>
          <div className="case-header__identity">
            <span className="mono">{activeCase.key}</span>
            <span aria-hidden="true">·</span>
            <span>{activeCase.title}</span>
          </div>
          <div className="case-header__meta">
            <span>
              {t("case.header.jurisdiction")}: {activeCase.jurisdiction}
            </span>
            <span>
              {t("case.status")}: {t(caseStatusLabels[activeCase.status])}
            </span>
            {activeCase.holdCount > 0 ||
            activeCase.integrityStatus === "hold" ? (
              <a
                className="badge badge--hold"
                href={routes.evidenceHolds(activeCase.id)}
                aria-label={t(
                  activeCase.holdCount === 1
                    ? "case.integrity.holds_one"
                    : "case.integrity.holds",
                  { count: activeCase.holdCount },
                )}
              >
                {t(
                  activeCase.holdCount === 1
                    ? "case.integrity.holds_one"
                    : "case.integrity.holds",
                  { count: activeCase.holdCount },
                )}
              </a>
            ) : activeCase.integrityStatus === "clear" ? (
              <span className="badge badge--ok">
                {t("case.integrity.all_clear")}
              </span>
            ) : activeCase.integrityStatus === "verifying" ? (
              <span className="badge badge--warn">
                {t("case.integrity.verifying")}
              </span>
            ) : (
              <span className="badge badge--idle">
                {t("case.integrity.unknown")}
              </span>
            )}
          </div>
        </section>
      )}

      <div className="shell__body">
        {activeCase && (
          <nav className="rail" aria-label={t("nav.case_nav")}>
            <ul className="rail__list">
              {sections.map((section) =>
                RAIL_BY_ROLE[session.role].includes(section) &&
                permissions.canSeeSection(section) ? (
                  <li key={section}>
                    <a
                      className={`rail__link${activeSection === section ? " is-active" : ""}`}
                      href={routes.caseSection(activeCase.id, section)}
                      aria-current={
                        activeSection === section ? "page" : undefined
                      }
                    >
                      <span className="rail__shape" aria-hidden="true" />
                      <span>{t(sectionLabels[section])}</span>
                    </a>
                  </li>
                ) : null,
              )}
            </ul>
          </nav>
        )}

        <main id="main" className="shell__main" tabIndex={-1}>
          {content}
        </main>

        {activeCase && (
          <aside
            id="right-drawer"
            ref={drawerRef}
            className="shell__drawer"
            aria-label={t("drawer.label")}
            aria-hidden={!drawerOpen}
            hidden={!drawerOpen}
            tabIndex={-1}
          >
            <DrawerContents
              item={selectedItem}
              locale={locale}
              timeZone={activeCase.timezone}
              onClose={closeDrawer}
              onVerify={onVerify ? verifySelectedItem : undefined}
              verificationError={verificationError}
              verifying={verifying}
            />
          </aside>
        )}
      </div>
    </div>
  );
}

function LocaleLink({
  locale,
  target,
}: {
  locale: Locale;
  target: Locale;
}) {
  const url = new URL(window.location.href);
  url.searchParams.set("lang", target);
  const label = translate(
    locale,
    target === "en" ? "language.en" : "language.fr",
  );
  return (
    <a
      href={`${url.pathname}${url.search}${url.hash}`}
      lang={target}
      aria-current={locale === target ? "true" : undefined}
      className={locale === target ? "is-active" : undefined}
    >
      {label}
    </a>
  );
}

function DrawerContents({
  item,
  locale,
  timeZone,
  onClose,
  onVerify,
  verificationError,
  verifying,
}: {
  item: DrawerObject | null;
  locale: Locale;
  timeZone: string;
  onClose: () => void;
  onVerify?: () => void;
  verificationError: string | null;
  verifying: boolean;
}) {
  const t = (key: MessageKey, parameters?: MessageParameters) =>
    translate(locale, key, parameters);

  if (!item) {
    return <p>{t("drawer.no_selection")}</p>;
  }

  const sections: Array<{
    id: string;
    title: string;
    content: ReactNode;
  }> = [
    {
      id: "drawer-custody",
      title: t("drawer.custody_history"),
      content: item.custody.length ? (
        <ol className="drawer__history">
          {item.custody.map((entry) => (
            <li key={entry.id} className="drawer__row">
              <span>
                {entry.actor === "system"
                  ? t("custody.actor.system")
                  : entry.actor}
              </span>
              <span>{t(custodyActionLabels[entry.action])}</span>
              <time className="mono" dateTime={entry.at}>
                {formatDateTime(locale, entry.at, timeZone)}
              </time>
              <span className="chain" data-chain={entry.chain}>
                <span className="sr-only">{t("chain.prefix")} </span>
                {t(chainLabels[entry.chain])}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p>{t("drawer.none")}</p>
      ),
    },
    {
      id: "drawer-provenance",
      title: t("drawer.provenance"),
      content: (
        <dl className="drawer__kv">
          <dt>{t("provenance.parent")}</dt>
          <dd>{item.parent ?? t("drawer.none")}</dd>
          <dt>{t("provenance.source")}</dt>
          <dd>{item.source}</dd>
          <dt>{t("provenance.parser")}</dt>
          <dd className="mono">{item.parserVersion}</dd>
        </dl>
      ),
    },
    {
      id: "drawer-verification",
      title: t("drawer.verification"),
      content: (
        <>
          <p>{t(verificationLabels[item.verification.outcome])}</p>
          {item.verification.failingStep && (
            <p>
              {t("verification.failing_step", {
                step: item.verification.failingStep,
              })}
            </p>
          )}
          {onVerify && (
            <button
              className="btn btn--primary"
              type="button"
              onClick={onVerify}
              disabled={verifying}
            >
              {verifying ? t("state.loading") : t("verification.verify_now")}
            </button>
          )}
          {verificationError && (
            <p className="form-error" role="alert">
              {verificationError}
            </p>
          )}
        </>
      ),
    },
    {
      id: "drawer-corrections",
      title: t("drawer.correction_history"),
      content: item.corrections.length ? (
        <ol className="drawer__history">
          {item.corrections.map((revision) => (
            <li key={revision.id} className="drawer__row">
              <span>{revision.extractedValue}</span>
              <span>{revision.reason}</span>
              <time className="mono" dateTime={revision.at}>
                {formatDateTime(locale, revision.at, timeZone)}
              </time>
            </li>
          ))}
        </ol>
      ) : (
        <p>{t("drawer.none")}</p>
      ),
    },
  ];

  return (
    <div className="drawer">
      <header className="drawer__header">
        <h2 id="drawer-title">{t("drawer.label")}</h2>
        <button
          className="drawer__close"
          type="button"
          onClick={onClose}
          aria-label={t("drawer.close")}
        >
          ×
        </button>
      </header>
      {sections.map((section) => (
        <section
          key={section.id}
          className="drawer__section"
          aria-labelledby={section.id}
        >
          <h3 id={section.id}>{section.title}</h3>
          {section.content}
        </section>
      ))}
    </div>
  );
}
