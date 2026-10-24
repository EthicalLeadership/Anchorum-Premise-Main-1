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
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportSuccess, setExportSuccess] = useState<string | null>(null);
  const t = (
    key: string,
    parameters?: Record<string, string | number>,
  ) => translate(locale, key as never, parameters as never);

  useEffect(() => {
    let active = true;
    setAudit({ kind: "loading" });
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

  const failedGate =
    preview.kind === "ready"
      ? preview.gates.find((gate) => gate.result === "fail")
      : undefined;

  async function onExport() {
    setExporting(true);
    setExportError(null);
    setExportSuccess(null);
    const result = await adapter.exports.generate(caseId, { includeSummary });
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
        {preview.kind === "loading" ? (
          <StateBlock locale={locale} kind="loading" />
        ) : preview.kind === "error" ? (
          <p role="alert">{preview.message}</p>
        ) : (
          <>
            <ul className="audit-exports__gates">
              {preview.gates.map((gate) => (
                <li key={gate.id} data-result={gate.result}>
                  <span>{t(`export.gate.${gate.id}`)}</span>
                  <strong>{t(`export.gate.${gate.result}`)}</strong>
                </li>
              ))}
            </ul>
            {failedGate?.failingItem ? (
              <p role="alert">
                {t("export.blocked", {
                  gate: t(`export.gate.${failedGate.id}`),
                  item: failedGate.failingItem,
                })}
              </p>
            ) : null}
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
