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
  const [filter, setFilter] = useState(() => (window.location.hash.includes("filter=hold") ? "hold" : "all"));

  useEffect(() => {
    let active = true;
    setLoad({ kind: "loading" });
    (async () => {
      const r = await adapter.evidence.list(caseId);
      if (!active) return;
      setLoad(r.ok ? { kind: "ready", rows: r.value } : { kind: "error", key: `error.${r.error.toLowerCase()}` });
    })();
    return () => {
      active = false;
    };
  }, [adapter, caseId, attempt]);

  const t = (k: string) => translate(locale, k as never);
  const retry = { label: t("state.retry"), onClick: () => setAttempt((n) => n + 1) };

  if (load.kind === "loading") return <StateBlock locale={locale} kind="loading" />;
  if (load.kind === "error") return <StateBlock locale={locale} kind="error" message={t(load.key)} action={retry} />;

  const rows = load.rows.filter((e) =>
    filter === "all" ? true : filter === "hold" ? e.status === "integrity_hold" : e.status === filter,
  );
  const columns: Column<Evidence>[] = [
    {
      id: "id",
      header: t("evidence.register.column.id"),
      render: (e) => <a href={`#/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(e.id)}`}>{e.id}</a>,
    },
    { id: "name", header: t("evidence.register.column.name"), render: (e) => e.name },
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
  ];

  return (
    <section className="register">
      <h1>{t("evidence.register.title")}</h1>
      <a href={`#/cases/${encodeURIComponent(caseId)}/intake`}>{t("evidence.intake.title")}</a>
      {" "}
      <a href={`#/cases/${encodeURIComponent(caseId)}/search`}>{t("search.title")}</a>
      <label>
        {t("evidence.register.filter.status")}
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">{t("evidence.register.filter.all")}</option>
          <option value="hold">{t("evidence.register.filter.hold")}</option>
          <option value="quarantined">{t("evidence.status.quarantined")}</option>
          <option value="preserved">{t("evidence.status.preserved")}</option>
          <option value="indexed">{t("evidence.status.indexed")}</option>
        </select>
      </label>
      {rows.length === 0 ? (
        <StateBlock locale={locale} kind="empty" message={t("evidence.register.empty")} />
      ) : (
        <DataTable caption={t("evidence.register.title")} columns={columns} rows={rows} rowKey={(e) => e.id} />
      )}
    </section>
  );
}
