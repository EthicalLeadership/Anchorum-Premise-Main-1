import { useEffect, useState } from "react";
import type { createAdapter, Evidence } from "../adapter";
import { StateBlock } from "../components/StateBlock";
import { DataTable, type Column } from "../components/DataTable";
import { translate } from "../i18n";
import type { Locale } from "../types";

type Props = { locale: Locale; adapter: ReturnType<typeof createAdapter>; caseId: string };
type Load = { kind: "loading" } | { kind: "error"; key: string } | { kind: "ready"; rows: readonly Evidence[] };

export function Register({ locale, adapter, caseId }: Props) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [filters, setFilters] = useState<import("../adapter").EvidenceFilters>(() =>
    window.location.hash.includes("filter=hold") ? { status: "hold" } : {},
  );
  const [removing, setRemoving] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoad({ kind: "loading" });
    (async () => {
      const r = await adapter.evidence.list(caseId, filters);
      if (!active) return;
      setLoad(r.ok ? { kind: "ready", rows: r.value } : { kind: "error", key: `error.${r.error.toLowerCase()}` });
    })();
    return () => {
      active = false;
    };
  }, [adapter, caseId, attempt, filters]);

  const t = (k: string) => translate(locale, k as never);
  const retry = { label: t("state.retry"), onClick: () => setAttempt((n) => n + 1) };
  async function onRemove(id: string) {
    if (!window.confirm(t("evidence.register.remove_confirm"))) return;
    setRemoving(id);
    setRemoveError(null);
    const r = await adapter.evidence.remove(id);
    setRemoving(null);
    if (!r.ok) {
      setRemoveError(t("error.evidence_remove_failed"));
      return;
    }
    setLoad((prev) =>
      prev.kind === "ready"
        ? { kind: "ready", rows: prev.rows.filter((row) => row.id !== id) }
        : prev,
    );
  }
  const caseNavigation = (
    <nav aria-label={t("nav.evidence_actions")}>
      <a href={`#/cases/${encodeURIComponent(caseId)}/overview`}>
        {t("nav.overview")}
      </a>
      {" · "}
      <a href="#/cases">{t("case.list.browse")}</a>
    </nav>
  );

  if (load.kind === "loading") return (
    <section className="register">
      {caseNavigation}
      <StateBlock locale={locale} kind="loading" />
    </section>
  );
  if (load.kind === "error") return (
    <section className="register">
      {caseNavigation}
      <StateBlock locale={locale} kind="error" message={t(load.key)} action={retry} />
    </section>
  );

  const rows = load.rows;
  const columns: Column<Evidence>[] = [
    {
      id: "id",
      header: t("evidence.register.column.id"),
      // The cell is width-capped and ellipsised in `register.css`, so the full
      // identifier stays reachable on hover rather than only via the viewer.
      render: (e) => (
        <a
          href={`#/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(e.id)}`}
          title={e.id}
        >
          {e.id}
        </a>
      ),
    },
    { id: "name", header: t("evidence.register.column.name"), render: (e) => e.name },
    {
      id: "category",
      header: t("evidence.register.column.category"),
      render: (e) => (e.category ? t(`evidence.category.${e.category}`) : "—"),
    },
    {
      id: "source",
      header: t("evidence.register.column.source"),
      render: (e) => (e.source ? t(`evidence.source.${e.source}`) : "—"),
    },
    { id: "status", header: t("evidence.register.column.status"), render: (e) => t(`evidence.status.${e.status}`) },
    {
      id: "badges",
      header: t("evidence.register.column.badges"),
      render: (e) => e.badges.map((b) => t(`badge.${b}`)).join(", "),
    },
    {
      id: "reason",
      header: t("evidence.register.column.reason"),
      render: (e) => {
        const r = e.quarantinedReason ?? e.holdReason;
        return r ? t(`reason.${r}`) : "";
      },
    },
    {
      id: "actions",
      header: t("evidence.register.column.actions"),
      render: (e) => (
        <button
          type="button"
          disabled={removing === e.id}
          onClick={() => onRemove(e.id)}
        >
          {t("evidence.register.action.remove")}
        </button>
      ),
    },
  ];

  return (
    <section className="register">
      <h1>{t("evidence.register.title")}</h1>
      {caseNavigation}
      <a href={`#/cases/${encodeURIComponent(caseId)}/intake`}>{t("evidence.intake.title")}</a>
      {" "}
      <a href={`#/cases/${encodeURIComponent(caseId)}/search`}>{t("search.title")}</a>
      <div className="register__filters">
        <label>
          {t("evidence.register.filter.category")}
          <select
            value={filters.category ?? ""}
            onChange={(e) => setFilters({ ...filters, category: e.target.value || undefined })}
          >
            <option value="">{t("evidence.register.filter.all_option")}</option>
            <option value="medical">{t("evidence.category.medical")}</option>
            <option value="payroll">{t("evidence.category.payroll")}</option>
            <option value="correspondence">{t("evidence.category.correspondence")}</option>
            <option value="pleading">{t("evidence.category.pleading")}</option>
            <option value="other">{t("evidence.category.other")}</option>
          </select>
        </label>
        <label>
          {t("evidence.register.filter.source")}
          <select
            value={filters.source ?? ""}
            onChange={(e) => setFilters({ ...filters, source: e.target.value || undefined })}
          >
            <option value="">{t("evidence.register.filter.all_option")}</option>
            <option value="clinic">{t("evidence.source.clinic")}</option>
            <option value="insurer">{t("evidence.source.insurer")}</option>
            <option value="employer">{t("evidence.source.employer")}</option>
            <option value="court">{t("evidence.source.court")}</option>
            <option value="other">{t("evidence.source.other")}</option>
          </select>
        </label>
        <label>
          {t("evidence.register.filter.document_type")}
          <select
            value={filters.documentType ?? ""}
            onChange={(e) => setFilters({ ...filters, documentType: e.target.value || undefined })}
          >
            <option value="">{t("evidence.register.filter.all_option")}</option>
            <option value="medical_note">{t("evidence.document_type.medical_note")}</option>
            <option value="payroll">{t("evidence.document_type.payroll")}</option>
            <option value="insurer_letter">{t("evidence.document_type.insurer_letter")}</option>
            <option value="official_report">{t("evidence.document_type.official_report")}</option>
            <option value="correspondence">{t("evidence.document_type.correspondence")}</option>
            <option value="unknown">{t("evidence.document_type.unknown")}</option>
          </select>
        </label>
        <label>
          {t("evidence.register.filter.author")}
          <input
            type="search"
            value={filters.author ?? ""}
            onChange={(e) => setFilters({ ...filters, author: e.target.value || undefined })}
          />
        </label>
        <label>
          {t("evidence.register.filter.date")}
          <input
            type="date"
            value={filters.date ?? ""}
            onChange={(e) => setFilters({ ...filters, date: e.target.value || undefined })}
          />
        </label>
        <button
          type="button"
          className="btn"
          onClick={() => setFilters({})}
        >
          {t("evidence.register.filter.clear")}
        </button>
      </div>
      {removeError ? (
        <StateBlock locale={locale} kind="error" message={removeError} />
      ) : null}
      {rows.length === 0 ? (
        <StateBlock locale={locale} kind="empty" message={t("evidence.register.empty")} />
      ) : (
        <DataTable caption={t("evidence.register.title")} columns={columns} rows={rows} rowKey={(e) => e.id} />
      )}
    </section>
  );
}
