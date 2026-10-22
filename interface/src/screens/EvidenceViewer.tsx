import { useEffect, useState } from "react";
import type { createAdapter, Evidence, CustodyEntry, EvidenceText } from "../adapter";
import { StateBlock } from "../components/StateBlock";
import { DataTable, type Column } from "../components/DataTable";
import { ChainTimeline } from "../components/ChainTimeline";
import { VerificationTile, type VerificationView } from "../components/VerificationTile";
import { PdfViewer } from "../components/PdfViewer";
import { ExtractedText } from "../components/ExtractedText";
import { formatDateTime, translate } from "../i18n";
import type { Locale } from "../types";

/** Only PDFs go through react-pdf; anything else keeps the plain link. */
function isPdf(name: string): boolean {
  return /\.pdf$/i.test(name);
}

type Props = { locale: Locale; adapter: ReturnType<typeof createAdapter>; caseId: string; evidenceId: string };
type TextLoad =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; key: string }
  | { kind: "ready"; value: EvidenceText };
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
  const [verifyingDoctrine, setVerifyingDoctrine] = useState(false);
  const [doctrineResult, setDoctrineResult] = useState<{ match: boolean; reason: string | null } | null>(null);
  const [tab, setTab] = useState<"original" | "extracted">("original");
  const [textLoad, setTextLoad] = useState<TextLoad>({ kind: "idle" });
  // Which panel the reader is on, and what the extracted-text fetch returned.
  // Kept beside the main load rather than inside it: the text is a second,
  // optional read, and failing to fetch it must not blank the original.

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

  // The extracted text is a second, optional read: fetched only when the reader
  // opens that panel, because most visits are to look at the original and the
  // sidecar can run to hundreds of thousands of characters.
  // Dependencies deliberately exclude `textLoad.kind`. Including it made the
  // effect re-run when it set "loading", and that re-run's cleanup flipped
  // `active` to false, so the resolved promise was discarded and the panel sat
  // on "Loading…" forever - a deadlock that only appears at runtime.
  useEffect(() => {
    if (tab !== "extracted") return;
    let active = true;
    setTextLoad((current) =>
      current.kind === "idle" ? { kind: "loading" } : current,
    );
    (async () => {
      const result = await adapter.evidence.text(evidenceId);
      if (!active) return;
      if (!result.ok) {
        setTextLoad({ kind: "error", key: "evidence.text.error" });
        return;
      }
      setTextLoad({ kind: "ready", value: result.value });
    })();
    return () => {
      active = false;
    };
  }, [adapter, evidenceId, tab]);

  // `translate` takes an optional parameter map and throws when a message
  // declares a placeholder it was not given. Forwarding that third argument is
  // what lets call sites supply `{reason}` rather than failing at render.
  const t = (k: string, parameters?: Record<string, string | number>) =>
    translate(locale, k as never, parameters);
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

  async function onVerifyDoctrine() {
    setVerifyingDoctrine(true);
    setDoctrineResult(null);
    const r = await adapter.evidence.verifyDoctrine(evidenceId);
    setVerifyingDoctrine(false);
    if (!r.ok) {
      setDoctrineResult({ match: false, reason: r.error });
      return;
    }
    setDoctrineResult({ match: r.value.match, reason: r.value.reason });
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
      <div className="evidence-tabs" role="tablist" aria-label={t("evidence.viewer.title")}>
        <button
          type="button"
          role="tab"
          id="tab-original"
          aria-selected={tab === "original"}
          aria-controls="panel-original"
          className="evidence-tabs__tab"
          onClick={() => setTab("original")}
        >
          {t("evidence.viewer.tab.original")}
        </button>
        <button
          type="button"
          role="tab"
          id="tab-extracted"
          aria-selected={tab === "extracted"}
          aria-controls="panel-extracted"
          className="evidence-tabs__tab"
          onClick={() => setTab("extracted")}
        >
          {t("evidence.viewer.tab.extracted")}
        </button>
      </div>
      {tab === "original" ? (
        <div role="tabpanel" id="panel-original" aria-labelledby="tab-original">
          {originalUrl ? (
            isPdf(evidence.name) ? (
              <PdfViewer locale={locale} fileUrl={originalUrl} />
            ) : (
              <p>
                <a href={originalUrl}>{t("evidence.viewer.download_original")}</a>
              </p>
            )
          ) : (
            <p role="status">{t("evidence.viewer.tab_unavailable")}</p>
          )}
        </div>
      ) : textLoad.kind === "ready" ? (
        <div role="tabpanel" id="panel-extracted" aria-labelledby="tab-extracted">
          <ExtractedText locale={locale} text={textLoad.value} />
        </div>
      ) : textLoad.kind === "error" ? (
        <div role="tabpanel" id="panel-extracted" aria-labelledby="tab-extracted">
          <p role="alert" className="form-error">{t(textLoad.key)}</p>
        </div>
      ) : (
        <div role="tabpanel" id="panel-extracted" aria-labelledby="tab-extracted">
          <p role="status">{t("evidence.text.loading")}</p>
        </div>
      )}
      <p>
        {t(`evidence.status.${evidence.status}`)}
        {evidence.badges.length > 0 ? ` · ${evidence.badges.map((b) => t(`badge.${b}`)).join(", ")}` : ""}
      </p>
      <p className="read-only">{t("evidence.viewer.read_only")}</p>
      <h2>{t("evidence.viewer.custody")}</h2>
      {custody.length === 0 ? (
        <StateBlock locale={locale} kind="empty" message={t("evidence.viewer.custody.empty")} />
      ) : (
        <>
          <ChainTimeline locale={locale} entries={custody} timeZone={timeZone} />
          <DataTable caption={t("evidence.viewer.custody")} columns={columns} rows={custody} rowKey={(r) => r.id} />
        </>
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
          onClick={onVerifyDoctrine}
          disabled={verifyingDoctrine}
        >
          {verifyingDoctrine ? t("evidence.viewer.verify_doctrine_loading") : t("evidence.viewer.verify_doctrine")}
        </button>
        {doctrineResult ? (
          doctrineResult.match
            ? <p role="status">{t("evidence.viewer.doctrine_match")}</p>
            : <p role="alert" className="form-error">{t("evidence.viewer.doctrine_mismatch", { reason: doctrineResult.reason ?? "unknown" })}</p>
        ) : null}
      </div>
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
