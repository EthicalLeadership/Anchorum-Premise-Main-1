import { useEffect, useMemo, useState } from "react";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { FilterBar } from "../components/FilterBar";
import type { CaseFilters } from "../components/FilterBar";
import { StateBlock } from "../components/StateBlock";
import { formatDateTime, translate } from "../i18n";
import type { Locale } from "../types";
import type { CaseRow, createAdapter } from "../adapter";

interface CaseListProps {
  locale: Locale;
  adapter: ReturnType<typeof createAdapter>;
  permissionLimited?: boolean;
}

type Load =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; rows: readonly CaseRow[] };

const noFilters: CaseFilters = { status: "", owner: "" };

export function CaseList({ locale, adapter, permissionLimited = false }: CaseListProps) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [filters, setFilters] = useState<CaseFilters>(noFilters);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setLoad({ kind: "loading" });
    adapter.cases.list().then((result) => {
      if (!active) return;
      setLoad(result.ok ? { kind: "ready", rows: result.value } : { kind: "error" });
    });
    return () => {
      active = false;
    };
  }, [adapter, attempt]);

  const rows = load.kind === "ready" ? load.rows : [];
  const visible = useMemo(
    () =>
      rows.filter(
        (r) =>
          (!filters.status || r.status === filters.status) &&
          (!filters.owner || r.ownerId === filters.owner),
      ),
    [rows, filters],
  );

  const columns: Column<CaseRow>[] = [
    {
      id: "key",
      header: translate(locale, "case.list.column.key"),
      render: (c) => <a href={`#/cases/${encodeURIComponent(c.id)}`}>{c.key}</a>,
    },
    { id: "title", header: translate(locale, "case.list.column.title"), render: (c) => c.title },
    {
      id: "status",
      header: translate(locale, "case.list.column.status"),
      render: (c) => translate(locale, `case.header.status.${c.status}` as never),
    },
    { id: "owner", header: translate(locale, "case.list.column.owner"), render: (c) => c.ownerId },
    {
      id: "evidence",
      header: translate(locale, "case.list.column.evidence_count"),
      render: (c) => c.evidenceCount,
    },
    { id: "holds", header: translate(locale, "case.list.column.holds"), render: (c) => c.holdCount },
    {
      id: "activity",
      header: translate(locale, "case.list.column.last_activity"),
      render: (c) => formatDateTime(locale, c.lastActivity, c.timezone),
    },
  ];

  const createLink = (
    <a className="btn btn--primary" href="#/cases/new">
      {translate(locale, "case.list.empty_action")}
    </a>
  );

  let body;
  if (permissionLimited) {
    body = <StateBlock locale={locale} kind="permission_limited" message={translate(locale, "case.list.permission_limited")} />;
  } else if (load.kind === "loading") {
    body = <StateBlock locale={locale} kind="loading" />;
  } else if (load.kind === "error") {
    body = (
      <StateBlock
        locale={locale}
        kind="error"
        message={translate(locale, "error.backend_unreachable")}
        action={{ label: translate(locale, "state.retry"), onClick: () => setAttempt((n) => n + 1) }}
      />
    );
  } else if (rows.length === 0) {
    body = (
      <StateBlock
        locale={locale}
        kind="empty"
        message={translate(locale, "case.list.empty")}
        action={{ label: translate(locale, "case.list.empty_action"), href: "#/cases/new" }}
      />
    );
  } else {
    body = (
      <>
        <FilterBar
          locale={locale}
          filters={filters}
          statuses={[...new Set(rows.map((r) => r.status))]}
          owners={[...new Set(rows.map((r) => r.ownerId))]}
          onChange={setFilters}
        />
        {visible.length === 0 ? (
          <StateBlock
            locale={locale}
            kind="empty"
            message={translate(locale, "case.list.no_matches")}
            action={{
              label: translate(locale, "case.list.no_matches_action"),
              onClick: () => setFilters(noFilters),
            }}
          />
        ) : (
          <DataTable
            caption={translate(locale, "case.list.title")}
            columns={columns}
            rows={visible}
            rowKey={(r) => r.id}
          />
        )}
      </>
    );
  }

  return (
    <section className="case-list" aria-labelledby="case-list-title">
      <header className="case-list__header">
        <h1 id="case-list-title">{translate(locale, "case.list.title")}</h1>
        {!permissionLimited && load.kind !== "loading" && rows.length > 0 ? createLink : null}
      </header>
      {body}
    </section>
  );
}
