import { useEffect, useState } from "react";
import type { createAdapter } from "../adapter";
import { StateBlock } from "../components/StateBlock";
import { VerificationTile, type VerificationView } from "../components/VerificationTile";
import { translate } from "../i18n";
import type { Locale } from "../types";

type Props = { locale: Locale; adapter: ReturnType<typeof createAdapter>; caseId: string };

type AuditRow = { id: string; event: string; chain: string };
type Load =
  | { kind: "loading" }
  | { kind: "error"; key: string }
  | {
      kind: "ready";
      timeZone: string;
      verification: VerificationView | null;
      activity: readonly AuditRow[];
    };

export function Overview({ locale, adapter, caseId }: Props) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setLoad({ kind: "loading" });
    (async () => {
      const c = await adapter.cases.get(caseId);
      if (!active) return;
      if (!c.ok) return setLoad({ kind: "error", key: `error.${c.error.toLowerCase()}` });
      const ev = await adapter.evidence.list(c.value.id);
      const audit = await adapter.audit.list(c.value.id);
      if (!active) return;
      let verification: VerificationView | null = null;
      if (ev.ok && ev.value.length > 0) {
        const target = ev.value.find((e) => e.status === "integrity_hold") ?? ev.value[0];
        const v = await adapter.evidence.verify(target.id);
        if (v.ok) verification = v.value as VerificationView;
      }
      if (!active) return;
      setLoad({
        kind: "ready",
        timeZone: c.value.timezone,
        verification,
        activity: audit.ok ? audit.value : [],
      });
    })();
    return () => {
      active = false;
    };
  }, [adapter, caseId, attempt]);

  if (load.kind === "loading") return <StateBlock locale={locale} kind="loading" />;
  if (load.kind === "error") {
    return (
      <StateBlock
        locale={locale}
        kind="error"
        message={translate(locale, load.key as never)}
        action={{ label: translate(locale, "state.retry"), onClick: () => setAttempt((n) => n + 1) }}
      />
    );
  }
  const base = `#/cases/${encodeURIComponent(caseId)}`;
  return (
    <section className="overview">
      <h1>{translate(locale, "overview.title")}</h1>
      {load.verification ? (
        <VerificationTile locale={locale} timeZone={load.timeZone} verification={load.verification} />
      ) : (
        <StateBlock locale={locale} kind="empty" />
      )}
      <section aria-labelledby="recent-title">
        <h2 id="recent-title">{translate(locale, "overview.recent_activity.title")}</h2>
        {load.activity.length === 0 ? (
          <StateBlock locale={locale} kind="empty" />
        ) : (
          <ul>
            {load.activity.map((a) => (
              <li key={a.id}>{translate(locale, `audit.event.${a.event}` as never)}</li>
            ))}
          </ul>
        )}
      </section>
      <nav className="quick-links">
        <a href={`${base}/evidence`}>{translate(locale, "overview.quick_links.evidence")}</a>{" "}
        <a href={`${base}/timeline`}>{translate(locale, "overview.quick_links.timeline")}</a>{" "}
        <a href={`${base}/audit`}>{translate(locale, "overview.quick_links.audit")}</a>
      </nav>
    </section>
  );
}
