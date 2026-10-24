import { useEffect, useState } from "react";




import type { AuditEntry, ExportGate, createAdapter } from "../adapter";
import { DataTable, type Column } from "../components/DataTable";
import { ProofsPanel } from "../components/ProofsPanel";
import { StateBlock } from "../components/StateBlock";
import { formatDateTime, translate } from "../i18n";
import type { Locale } from "../types";

type Props = {
  locale: Locale;
  adapter: ReturnType<typeof createAdapter>;
  caseId: string;
};
type ExportType = "evidence_index" | "signed_audit_package";
/** Gates whose outcome needs a sentence of explanation, keyed by gate then
 *  result. A bare `not_checked` row reads like a pass that was mislabelled, so
 *  the gates that can end that way say why. */
const GATE_NOTE: Record<string, Record<string, string>> = {
  provenance: { warn: "export.gate.provenance.note" },
  audit_hmac: { not_checked: "export.gate.audit_hmac.note" },
  projection_rules: { not_checked: "export.gate.projection_rules.note" },
  control_chain: { not_checked: "export.gate.control_chain.note" },
};
type AuditLoad =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; rows: readonly AuditEntry[]; timeZone: string };
type PreviewLoad =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; gates: readonly ExportGate[]; blocked: boolean };

const exportTypes: readonly ExportType[] = [
  "evidence_index",
  "signed_audit_package",
];

export function AuditExports({ locale, adapter, caseId }: Props) {
  const [audit, setAudit] = useState<AuditLoad>({ kind: "loading" });
  const [preview, setPreview] = useState<PreviewLoad>({ kind: "loading" });
  const [exportType, setExportType] = useState<ExportType>(exportTypes[0]);
  const [attempt, setAttempt] = useState(0);
  const [includeSummary, setIncludeSummary] = useState(true);
  const [format, setFormat] = useState<"zip" | "pdf">("zip");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportSuccess, setExportSuccess] = useState<string | null>(null);
  const t = (
    key: string,
    parameters?: Record<string, string | number>,
  ) => translate(locale, key as never, parameters as never);

  useEffect(() => {
    let active = true;
    // Only the first load shows a spinner. A refresh (after a verification or
    // an export) keeps the current rows on screen: dropping to "loading" would
    // unmount this subtree, and anything holding state inside it — the
    // proofs panel's results, for one — would be discarded the moment it
    // finished its work.
    setAudit((current) => (current.kind === "ready" ? current : { kind: "loading" }));
    Promise.all([adapter.cases.get(caseId), adapter.audit.list(caseId)]).then(
      ([caseResult, auditResult]) => {
        if (!active) return;
        if (!caseResult.ok) {
          setAudit({
            kind: "error",
            message: t(`error.${caseResult.error.toLowerCase()}`),
          });
          return;
        }
        if (!auditResult.ok) {
          setAudit({
            kind: "error",
            message: t(`error.${auditResult.error.toLowerCase()}`),
          });
          return;
        }
        setAudit({
          kind: "ready",
          rows: auditResult.value,
          timeZone: caseResult.value.timezone,
        });
      },
    );
    return () => {
      active = false;
    };
  }, [adapter, caseId, attempt, locale]);

  useEffect(() => {
    let active = true;
    setPreview({ kind: "loading" });
    adapter.exports.preview(caseId, exportType).then((result) => {
      if (!active) return;
      setPreview(
        result.ok
          ? {
              kind: "ready",
              gates: result.value.gates as readonly ExportGate[],
              blocked: result.value.blocked,
            }
          : {
              kind: "error",
              message: t(`error.${result.error.toLowerCase()}`),
            },
      );
    });
    return () => {
      active = false;
    };
  }, [adapter, caseId, exportType, attempt, locale]);

  if (audit.kind === "loading") return <StateBlock locale={locale} kind="loading" />;
  if (audit.kind === "error") {
    return (
      <StateBlock
        locale={locale}
        kind="error"
        message={audit.message}
        action={{ label: t("state.retry"), onClick: () => setAttempt((n) => n + 1) }}
      />
    );
  }

  const columns: Column<AuditEntry>[] = [
    {
      id: "time",
      header: t("audit.column.time"),
      render: (entry) =>
        "at" in entry
          ? formatDateTime(locale, entry.at, audit.timeZone)
          : "",
    },
    {
      id: "actor",
      header: t("audit.column.actor"),
      render: (entry) => ("actor" in entry ? entry.actor : t("custody.actor.system")),
    },
    {
      id: "event",
      header: t("audit.column.event"),
      render: (entry) => t(`audit.event.${entry.event}`),
    },
    {
      id: "object",
      header: t("audit.column.object"),
      render: (entry) =>
        "evidenceId" in entry && entry.evidenceId
          ? (
              <a href={`#/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(entry.evidenceId)}`}>
                {entry.evidenceId}
              </a>
            )
          : "memberId" in entry
            ? entry.memberId
            : "",
    },
    {
      id: "chain",
      header: t("audit.column.chain"),
      render: (entry) => (
        <span className={`audit-chain audit-chain--${entry.chain}`}>
          {t(`chain.${entry.chain}`)}
          {"failingStep" in entry && entry.failingStep
            ? ` ${t(`reason.${entry.failingStep}`)}`
            : ""}
        </span>
      ),
    },
  ];

  // Only a blocking failure stops the export, so only a blocking failure earns
  // the "Export blocked" copy. An advisory gate that failed is reported in the
  // list and recorded in the package; it is not a block.
  const failedGate =
    preview.kind === "ready"
      ? preview.gates.find(
          (gate) => gate.result === "fail" && gate.blocking !== false,
        )
      : undefined;

  async function onExport() {
    setExporting(true);
    setExportError(null);
    setExportSuccess(null);
    const result = await adapter.exports.generate(caseId, { includeSummary, format });
    setExporting(false);
    if (!result.ok) {
      setExportError(t(`error.${result.error.toLowerCase()}`));
      return;
    }
    const url = URL.createObjectURL(result.value.blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = result.value.filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setExportSuccess(result.value.filename);
    setAttempt((n) => n + 1);
  }

  return (
    <section className="audit-exports" aria-labelledby="audit-title">
      <h1 id="audit-title">{t("audit.title")}</h1>
      {audit.rows.length === 0 ? null : (() => {
        // `chain` = evidence-verification outcome; `chainIntegrity` = audit-chain
        // state. Either failure means the badge must not read "Chain verified".
        // Older adapters that don't send chainIntegrity fall back to chain-only
        // detection (existing test behaviour preserved).
        const broken = audit.rows.find(
          (row) =>
            row.chain === "broken" ||
            ("chainIntegrity" in row && row.chainIntegrity === "broken"),
        );
        return broken ? (
          <p
            role="status"
            data-testid="chain-summary"
            className="audit-chain-summary audit-chain-summary--broken"
          >
            {t("chain.summary.broken_at", { id: broken.id })}
          </p>
        ) : (
          <p
            role="status"
            data-testid="chain-summary"
            className="audit-chain-summary audit-chain-summary--verified"
          >
            {t("chain.summary.verified")}
          </p>
        );
      })()}
      {audit.rows.length === 0 ? (
        <StateBlock locale={locale} kind="empty" />
      ) : (
        <DataTable
          caption={t("audit.title")}
          columns={columns}
          rows={audit.rows}
          rowKey={(entry) => entry.id}
        />
      )}

      <ProofsPanel
        locale={locale}
        adapter={adapter}
        caseId={caseId}
        timeZone={audit.timeZone}
        onVerified={() => setAttempt((n) => n + 1)}
      />

      <section aria-labelledby="export-title">
        <h2 id="export-title">{t("export.title")}</h2>
        <label>
          {t("export.title")}
          <select
            value={exportType}
            onChange={(event) => setExportType(event.target.value as ExportType)}
          >
            {exportTypes.map((type) => (
              <option key={type} value={type}>
                {t(`export.type.${type}`)}
              </option>
            ))}
          </select>
        </label>
        <h3>{t("export.preview.title")}</h3>
          <label>
            {t("export.format.label")}
            <select
              value={format}
              onChange={(event) => setFormat(event.target.value as 'zip' | 'pdf')}
            >
              <option value="zip">{t('export.format.zip')}</option>
              <option value="pdf">{t('export.format.pdf')}</option>
            </select>
          </label>
        {preview.kind === "loading" ? (
          <StateBlock locale={locale} kind="loading" />
        ) : preview.kind === "error" ? (
          <p role="alert">{preview.message}</p>
        ) : (
          <>
            <ul className="audit-exports__gates">
              {preview.gates.map((gate) => {
                const advisory = gate.blocking === false;
                const noteKey = GATE_NOTE[gate.id]?.[gate.result];
                return (
                  <li
                    key={gate.id}
                    data-result={gate.result}
                    data-blocking={advisory ? "false" : "true"}
                  >
                    <span className="audit-exports__gate-name">
                      {t(`export.gate.${gate.id}`)}
                      {advisory ? ` ${t("export.gate.advisory")}` : ""}
                    </span>
                    <strong
                      className={`audit-exports__gate-result audit-exports__gate-result--${gate.result}`}
                    >
                      {t(`export.gate.${gate.result}`)}
                    </strong>
                    {gate.failingItem ? (
                      <em className="audit-exports__gate-item">{gate.failingItem}</em>
                    ) : null}
                    {noteKey ? (
                      <span className="audit-exports__gate-note">{t(noteKey)}</span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
            {failedGate?.failingItem ? (
              <p role="alert">
                {t("export.blocked", {
                  gate: t(`export.gate.${failedGate.id}`),
                  item: failedGate.failingItem,
                })}
              </p>
            ) : null}
            <label className="export-format">
              <span>{t("export.format.label")}</span>
              <select
                value={format}
                onChange={(e) => setFormat(e.target.value as "zip" | "pdf")}
                disabled={exporting || preview.blocked}
                aria-label={t("export.format.label")}
              >
                <option value="zip">{t("export.format.zip")}</option>
                <option value="pdf">{t("export.format.pdf")}</option>
              </select>
            </label>
            <label className="export-summary-toggle">
              <input type="checkbox" checked={includeSummary} onChange={(e) => setIncludeSummary(e.target.checked)} />
              {t("export.summary.toggle")}
            </label>

            <button
              type="button"
              className="btn btn--primary"
              disabled={preview.blocked || exporting}
              onClick={onExport}
              aria-describedby={preview.blocked ? "export-blocked-help" : undefined}
            >
              {exporting ? "Exporting…" : t("export.action.export")}
            </button>
            {exportError ? (
              <p role="alert" className="form-error">{exportError}</p>
            ) : null}
            {exportSuccess ? (
              <p role="status">Downloaded {exportSuccess}</p>
            ) : null}
            {preview.blocked ? (
              <p id="export-blocked-help">
                {t("export.blocked", {
                  gate: t(`export.gate.${failedGate?.id ?? "barreau"}`),
                  item: failedGate?.failingItem ?? "",
                })}
              </p>
            ) : null}
          </>
        )}
      </section>
    </section>
  );
}
