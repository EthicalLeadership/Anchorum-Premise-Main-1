import { useCallback, useEffect, useRef, useState } from "react";
import type {
  createAdapter,
  CustodyEntry,
  Evidence,
  EvidenceText,
  SummaryResult,
} from "../adapter";
import { StateBlock } from "../components/StateBlock";
import { DataTable, type Column } from "../components/DataTable";
import { ChainTimeline } from "../components/ChainTimeline";
import { VerificationTile, type VerificationView } from "../components/VerificationTile";
import { PdfViewer } from "../components/PdfViewer";
import { ExtractedText } from "../components/ExtractedText";
import { SaulSummaryDrawer } from "../components/SaulSummaryDrawer";
import { formatDateTime, translate } from "../i18n";
import type { Locale } from "../types";

/** Only PDFs go through react-pdf; anything else keeps the plain link. */
function isPdf(name: string): boolean {
  return /\.pdf$/i.test(name);
}

function truncateHash(h: string): string {
  return h.length > 16 ? `${h.slice(0, 8)}…${h.slice(-4)}` : h;
}

const INTEGRITY_STEPS = ["hash", "signature", "chain", "anchor"] as const;
type IntegrityStep = (typeof INTEGRITY_STEPS)[number];

/**
 * The step an integrity hold blames.
 *
 * `holdReason` is `<step>_<detail>`: `hash_mismatch_at_readback` means the hash
 * step disagreed with the bytes. Returns null when the reason names no known
 * step, so an unfamiliar reason renders as an unattributed hold rather than
 * being mislabelled with a step that did not fail.
 */
function holdStepId(holdReason: string | null): IntegrityStep | null {
  const head = (holdReason ?? "").split("_")[0];
  return (INTEGRITY_STEPS as readonly string[]).includes(head)
    ? (head as IntegrityStep)
    : null;
}

type Props = {
  locale: Locale;
  adapter: ReturnType<typeof createAdapter>;
  caseId: string;
  evidenceId: string;
};
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
  const [verifyingDoctrine, setVerifyingDoctrine] = useState(false);
  const [doctrineResult, setDoctrineResult] = useState<{
    match: boolean;
    reason: string | null;
  } | null>(null);

  // The summary drawer. `summary` is the last result the API produced, whether
  // it came from this click or from the record; `summaryLoading` covers both
  // paths so the drawer never shows an empty document while it waits.
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [summary, setSummary] = useState<SummaryResult | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const summaryTriggerRef = useRef<HTMLButtonElement | null>(null);

  // A search hit links here with `?at=<offset>&q=<term>`. Opening on the
  // original tab would drop the reader at the top of the PDF and lose the
  // position they just clicked, so the arriving link decides the tab.
  const arrivalParams = new URLSearchParams(window.location.hash.split("?")[1] ?? "");
  const arrivalAt = Number(arrivalParams.get("at"));
  const arrivalTerm = arrivalParams.get("q") ?? "";
  const arrival =
    arrivalTerm.length > 0 && Number.isFinite(arrivalAt) && arrivalAt >= 0
      ? { at: arrivalAt, term: arrivalTerm }
      : null;
  const [tab, setTab] = useState<"original" | "extracted">(
    arrival ? "extracted" : "original",
  );
  const [textLoad, setTextLoad] = useState<TextLoad>({ kind: "idle" });

  useEffect(() => {
    // A route can be reached with a placeholder id (a link built from an item
    // that had none). Requesting "null" would 404 and show a scare message for
    // what is really a missing link, so nothing is fetched for it — but the
    // check lives inside the effect, because a `return null` above the hooks
    // would call a different number of hooks on different renders.
    if (!evidenceId || evidenceId === "null") return;
    let active = true;
    setLoad({ kind: "loading" });
    (async () => {
      const [c, e, cu] = await Promise.all([
        adapter.cases.get(caseId),
        adapter.evidence.get(evidenceId),
        adapter.evidence.custody(evidenceId),
      ]);
      if (!active) return;
      const err = [c, e, cu].find((r) => !r.ok);
      if (err && !err.ok) {
        return setLoad({ kind: "error", key: `error.${err.error.toLowerCase()}` });
      }
      if (!c.ok || !e.ok || !cu.ok) return;
      setLoad({
        kind: "ready",
        evidence: e.value,
        custody: cu.value,
        verification: null,
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
  // on "Loading…" forever — a deadlock that only appears at runtime.
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

  // Reading the stored summary is a GET: it never calls the model, so opening
  // the drawer twice costs nothing and shows the same text both times.
  const openStoredSummary = useCallback(async () => {
    setSummaryOpen(true);
    setSummaryLoading(true);
    setSummaryError(null);
    const result = await adapter.evidence.summary(evidenceId);
    setSummaryLoading(false);
    if (!result.ok) {
      // NOT_GENERATED is the ordinary case: nothing has been asked for yet. It
      // is not an error and must not be dressed as one.
      if (result.error !== "HTTP_404") {
        setSummaryError(
          t(
            result.error === "FEATURE_UNAVAILABLE"
              ? "evidence.viewer.summary_unavailable"
              : "error.generic",
          ),
        );
      }
      return;
    }
    setSummary(result.value);
  }, [adapter, evidenceId, locale]);



  async function onSummarize() {
    setSummaryOpen(true);
    setSummaryLoading(true);
    setSummaryError(null);
    const result = await adapter.evidence.summarize(evidenceId);
    setSummaryLoading(false);
    if (!result.ok) {
      setSummaryError(
        t(
          result.error === "FEATURE_UNAVAILABLE"
            ? "evidence.viewer.summary_unavailable"
            : "error.generic",
        ),
      );
      return;
    }
    setSummary(result.value);
    // The custody list gained a "summarised" row; refetch so the reader sees
    // that this just happened rather than a list that stops before it.
    setAttempt((n) => n + 1);
  }

  async function onConsult() {
    setConsulting(true);
    setConsultError(null);
    const r = await adapter.evidence.consult(evidenceId);
    setConsulting(false);
    if (!r.ok) {
      setConsultError(
        t(
          r.error === "FEATURE_UNAVAILABLE"
            ? "evidence.viewer.ask_saul_unavailable"
            : "error.generic",
        ),
      );
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

  // Rendered, not fetched: an id that cannot address an item shows nothing
  // rather than an error that would blame the reader for a broken link.
  if (!evidenceId || evidenceId === "null") return null;

  const back = (
    <nav aria-label={t("nav.evidence_actions")}>
      <a href={`#/cases/${encodeURIComponent(caseId)}/register`}>
        {t("evidence.viewer.back")}
      </a>
      {" · "}
      <a href="#/cases">{t("case.list.browse")}</a>
    </nav>
  );

  if (load.kind === "loading")
    return (
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
      render: (r) => <span data-chain={r.chain}>{t(`chain.${r.chain}`)}</span>,
    },
  ];

  const latestHmac =
    custody.length > 0 ? (custody[custody.length - 1].hmac ?? "") : "";
  // Which step the hold blames, if the reason names one. Derived rather than
  // fetched: the reason is already on the record, and re-running verification
  // to learn why the last one failed would mean a POST on every page view.
  const failingStep = holdStepId(evidence.holdReason);
  const onHold = evidence.status === "integrity_hold";

  return (
    <section className="evidence-viewer">
      {back}
      <h1>
        {t("evidence.viewer.title")}: {evidence.id}
      </h1>
      <p>{evidence.name}</p>
      <dl className="evidence-metadata" data-testid="evidence-metadata">
        <dt>{t("evidence.viewer.metadata.sha256")}</dt>
        <dd title={evidence.sha256 ?? ""}>
          {evidence.sha256
            ? truncateHash(evidence.sha256)
            : t("evidence.viewer.metadata.unavailable")}
        </dd>
        <dt>{t("evidence.viewer.metadata.hmac")}</dt>
        <dd title={latestHmac || ""}>
          {latestHmac ? truncateHash(latestHmac) : t("evidence.viewer.metadata.unsigned")}
        </dd>
      </dl>

      {onHold ? (
        <p role="alert" className="form-error">
          {failingStep
            ? t("overview.integrity.hold", {
                step: t(`overview.integrity.step.${failingStep}`),
              })
            : t("overview.integrity.hold_unknown")}
        </p>
      ) : null}

      <div
        className="evidence-tabs"
        role="tablist"
        aria-label={t("evidence.viewer.title")}
      >
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
          <ExtractedText locale={locale} text={textLoad.value} highlight={arrival} />
        </div>
      ) : textLoad.kind === "error" ? (
        <div role="tabpanel" id="panel-extracted" aria-labelledby="tab-extracted">
          <p role="alert" className="form-error">
            {t(textLoad.key)}
          </p>
        </div>
      ) : (
        <div role="tabpanel" id="panel-extracted" aria-labelledby="tab-extracted">
          <p role="status">{t("evidence.text.loading")}</p>
        </div>
      )}

      <p>
        {t(`evidence.status.${evidence.status}`)}
        {evidence.badges.length > 0
          ? ` · ${evidence.badges.map((b) => t(`badge.${b}`)).join(", ")}`
          : ""}
      </p>

      {/* Ask Saul — the narrative summary. Always offered, because a document
          the deterministic analyser understood perfectly is still a document a
          reader may want summarised. */}
      <div className="evidence-actions">
        <button
          type="button"
          className="btn btn--primary"
          onClick={() => void onSummarize()}
          disabled={summaryLoading}
          ref={summaryTriggerRef}
        >
          {summaryLoading
            ? t("evidence.viewer.ask_summarize_loading")
            : t("evidence.viewer.ask_summarize")}
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => void openStoredSummary()}
          disabled={summaryLoading}
        >
          {t("evidence.viewer.summary.open")}
        </button>
      </div>
      {summaryError ? (
        <p role="alert" className="form-error">
          {summaryError}
        </p>
      ) : null}

      {evidence.analysis?.documentType === "unknown" ? (
        <div className="ask-saul">
          {evidence.consultation ? (
            <div>
              <h3>{t("evidence.viewer.consultation_label")}</h3>
              <dl className="consultation">
                <dt>{t("evidence.viewer.consultation_document_type")}</dt>
                <dd>{evidence.consultation.documentType}</dd>
                <dt>{t("evidence.viewer.consultation_model")}</dt>
                <dd className="mono">{evidence.consultation.model ?? "—"}</dd>
                {evidence.consultation.error ? (
                  <>
                    <dt>{t("evidence.viewer.consultation_error")}</dt>
                    <dd role="alert" className="form-error">
                      {evidence.consultation.error}
                    </dd>
                  </>
                ) : null}
              </dl>
            </div>
          ) : (
            <button
              type="button"
              className="btn"
              onClick={() => void onConsult()}
              disabled={consulting}
            >
              {consulting
                ? t("evidence.viewer.ask_saul_loading")
                : t("evidence.viewer.ask_saul")}
            </button>
          )}
          {consultError ? (
            <p role="alert" className="form-error">
              {consultError}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="evidence-actions">
        <button
          type="button"
          className="btn"
          onClick={() => void onVerifyDoctrine()}
          disabled={verifyingDoctrine}
        >
          {verifyingDoctrine
            ? t("evidence.viewer.verify_doctrine_loading")
            : t("evidence.viewer.verify_doctrine")}
        </button>
        {doctrineResult ? (
          doctrineResult.match ? (
            <p role="status">{t("evidence.viewer.doctrine_match")}</p>
          ) : (
            <p role="alert" className="form-error">
              {t("evidence.viewer.doctrine_mismatch", {
                reason: doctrineResult.reason ?? "unknown",
              })}
            </p>
          )
        ) : null}
      </div>

      <h2>{t("evidence.viewer.custody")}</h2>
      {custody.length === 0 ? (
        <StateBlock
          locale={locale}
          kind="empty"
          message={t("evidence.viewer.custody.empty")}
        />
      ) : (
        <>
          <ChainTimeline locale={locale} entries={custody} timeZone={timeZone} />
          <DataTable
            caption={t("evidence.viewer.custody")}
            columns={columns}
            rows={custody}
            rowKey={(r) => r.id}
          />
        </>
      )}

      <h2>{t("evidence.viewer.verification")}</h2>
      {verification ? (
        <VerificationTile locale={locale} timeZone={timeZone} verification={verification} />
      ) : onHold ? (
        // An item on hold has a failed verification on record. Saying "not yet
        // verified" here would contradict the hold alert higher up the page.
        <p role="status">{t("verification.failed_on_record")}</p>
      ) : (
        <p role="status">{t("verification.not_yet_verified")}</p>
      )}

      <SaulSummaryDrawer
        locale={locale}
        open={summaryOpen}
        loading={summaryLoading}
        summary={summary}
        timeZone={timeZone}
        onClose={() => {
          setSummaryOpen(false);
          summaryTriggerRef.current?.focus();
        }}
      />

    </section>
  );
}
