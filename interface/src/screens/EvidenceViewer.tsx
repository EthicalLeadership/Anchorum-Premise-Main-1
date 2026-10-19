import { useEffect, useState } from "react";
import type { createAdapter, Evidence, CustodyEntry } from "../adapter";
import { StateBlock } from "../components/StateBlock";
import { DataTable, type Column } from "../components/DataTable";
import { VerificationTile, type VerificationView } from "../components/VerificationTile";
import { formatDateTime, translate } from "../i18n";
import type { Locale } from "../types";

type Props = { locale: Locale; adapter: ReturnType<typeof createAdapter>; caseId: string; evidenceId: string };
type Load =
  | { kind: "loading" }
  | { kind: "error"; key: string }
  | {
      kind: "ready";
      evidence: Evidence;
      custody: readonly CustodyEntry[];
      verification: VerificationView | null;
      timeZone: string;
    };

export function EvidenceViewer({ locale, adapter, caseId, evidenceId }: Props) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [consulting, setConsulting] = useState(false);
  const [consultError, setConsultError] = useState<string | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [summarizeError, setSummarizeError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoad({ kind: "loading" });
    (async () => {
      const [c, e, cu, v] = await Promise.all([
        adapter.cases.get(caseId),
        adapter.evidence.get(evidenceId),
        adapter.evidence.custody(evidenceId),
        adapter.evidence.verify(evidenceId),
      ]);
      if (!active) return;
      const err = [c, e, cu].find((r) => !r.ok);
      if (err && !err.ok) return setLoad({ kind: "error", key: `error.${err.error.toLowerCase()}` });
      if (!c.ok || !e.ok || !cu.ok) return;
      setLoad({
        kind: "ready",
        evidence: e.value,
        custody: cu.value,
        verification: v.ok ? (v.value as VerificationView) : null,
        timeZone: c.value.timezone,
      });
    })();
    return () => {
      active = false;
    };
  }, [adapter, caseId, evidenceId, attempt]);

  const t = (k: string) => translate(locale, k as never);
  async function onConsult() {
    setConsulting(true);
    setConsultError(null);
    const r = await adapter.evidence.consult(evidenceId);
    setConsulting(false);
    if (!r.ok) {
      setConsultError(t(r.error === "FEATURE_UNAVAILABLE" ? "evidence.viewer.ask_saul_unavailable" : "error.generic"));
      return;
    }
    setAttempt((n) => n + 1); // Refetch evidence to pick up the new consultation.
  }

  async function onSummarize() {
    setSummarizing(true);
    setSummarizeError(null);
    const r = await adapter.evidence.summarize(evidenceId);
    setSummarizing(false);
    if (!r.ok) {
      setSummarizeError(t(r.error === "FEATURE_UNAVAILABLE" ? "evidence.viewer.ask_summarize_unavailable" : "error.generic"));
      return;
    }
    setAttempt((n) => n + 1);
  }

  const back = (
    <nav aria-label={t("nav.evidence_actions")}>
      <a href={`#/cases/${encodeURIComponent(caseId)}/register`}>{t("evidence.viewer.back")}</a>
      {" · "}
      <a href="#/cases">{t("case.list.browse")}</a>
    </nav>
  );

  if (load.kind === "loading") return (
    <section className="evidence-viewer">
      {back}
      <StateBlock locale={locale} kind="loading" />
    </section>
  );
  if (load.kind === "error")
    return (
      <section className="evidence-viewer">
        {back}
        <StateBlock
          locale={locale}
          kind="error"
          message={t(load.key)}
          action={{ label: t("state.retry"), onClick: () => setAttempt((n) => n + 1) }}
        />
      </section>
    );

  const { evidence, custody, verification, timeZone } = load;
  const originalUrl = adapter.evidence.originalUrl(evidenceId);
  const columns: Column<CustodyEntry>[] = [
    { id: "action", header: t("custody.column.action"), render: (r) => t(`custody.${r.action}`) },
    { id: "actor", header: t("custody.column.actor"), render: (r) => t(`custody.actor.${r.actor}`) },
    { id: "at", header: t("custody.column.at"), render: (r) => formatDateTime(locale, r.at, timeZone) },
    {
      id: "chain",
      header: t("custody.column.chain"),
      render: (r) => (
        <span data-chain={r.chain}>{t(`chain.${r.chain}`)}</span>
      ),
    },
  ];

  return (
    <section className="evidence-viewer">
      {back}
      <h1>{t("evidence.viewer.title")}: {evidence.id}</h1>
      <p>{evidence.name}</p>
      {originalUrl ? (
        <p>
          <a href={originalUrl}>{t("evidence.viewer.download_original")}</a>
        </p>
      ) : null}
      <p>
        {t(`evidence.status.${evidence.status}`)}
        {evidence.badges.length > 0 ? ` · ${evidence.badges.map((b) => t(`badge.${b}`)).join(", ")}` : ""}
      </p>
      <p className="read-only">{t("evidence.viewer.read_only")}</p>
      <h2>{t("evidence.viewer.custody")}</h2>
      {custody.length === 0 ? (
        <StateBlock locale={locale} kind="empty" message={t("evidence.viewer.custody.empty")} />
      ) : (
        <DataTable caption={t("evidence.viewer.custody")} columns={columns} rows={custody} rowKey={(r) => r.id} />
      )}
      {evidence.analysis?.documentType === "unknown" ? (
        <div className="ask-saul">
          {evidence.consultation ? (
            <div>
              <h3>{t("evidence.viewer.consultation_label")}</h3>
              <pre className="consultation-text">{evidence.consultation}</pre>
            </div>
          ) : (
            <button
              type="button"
              className="btn btn--primary"
              onClick={onConsult}
              disabled={consulting}
            >
              {consulting ? t("evidence.viewer.ask_saul_loading") : t("evidence.viewer.ask_saul")}
            </button>
          )}
          {consultError ? <p role="alert" className="form-error">{consultError}</p> : null}
        </div>
      ) : null}
      <div style={{ marginBottom: "1rem" }}>
        <button
          type="button"
          className="btn"
          onClick={onSummarize}
          disabled={summarizing}
        >
          {summarizing ? t("evidence.viewer.ask_summarize_loading") : t("evidence.viewer.ask_summarize")}
        </button>
        {summarizeError ? <p role="alert" className="form-error">{summarizeError}</p> : null}
      </div>
      <h2>{t("evidence.viewer.verification")}</h2>
      {verification ? (
        <VerificationTile locale={locale} timeZone={timeZone} verification={verification} />
      ) : (
        <p role="status">{t("verification.not_yet_verified")}</p>
      )}
    </section>
  );
}
