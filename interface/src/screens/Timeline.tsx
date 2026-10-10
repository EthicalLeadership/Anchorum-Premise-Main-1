import { useEffect, useMemo, useState } from "react";
import type { createAdapter, TimelineEvent } from "../adapter";
import { StateBlock } from "../components/StateBlock";
import { TimelineItem } from "../components/TimelineItem";
import { translate } from "../i18n";
import type { Locale } from "../types";

type Props = {
  locale: Locale;
  adapter: ReturnType<typeof createAdapter>;
  caseId: string;
};
type Load =
  | { kind: "loading" }
  | { kind: "error"; key: string }
  | { kind: "ready"; rows: readonly TimelineEvent[] };

export function Timeline({ locale, adapter, caseId }: Props) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [dateFilter, setDateFilter] = useState("");
  const [personFilter, setPersonFilter] = useState("");
  const [evidenceFilter, setEvidenceFilter] = useState("");
  const t = (key: string, parameters?: Record<string, string | number>) =>
    translate(locale, key as never, parameters as never);

  useEffect(() => {
    let active = true;
    setLoad({ kind: "loading" });
    adapter.timeline.list(caseId).then((result) => {
      if (!active) return;
      setLoad(
        result.ok
          ? { kind: "ready", rows: result.value }
          : { kind: "error", key: `error.${result.error.toLowerCase()}` },
      );
    });
    return () => {
      active = false;
    };
  }, [adapter, caseId]);

  const people = useMemo(
    () =>
      load.kind === "ready"
        ? [...new Set(load.rows.flatMap((row) => row.people))].sort()
        : [],
    [load],
  );
  const evidenceIds = useMemo(
    () =>
      load.kind === "ready"
        ? [...new Set(load.rows.map((row) => row.evidenceId))].sort()
        : [],
    [load],
  );

  if (load.kind === "loading") return <StateBlock locale={locale} kind="loading" />;
  if (load.kind === "error") {
    return (
      <StateBlock
        locale={locale}
        kind="error"
        message={t(load.key)}
      />
    );
  }

  const rows = load.rows.filter(
    (row) =>
      (!dateFilter || (row.date ?? "").includes(dateFilter.trim())) &&
      (!personFilter || row.people.some((person) => person === personFilter)) &&
      (!evidenceFilter || row.evidenceId === evidenceFilter),
  );

  return (
    <section className="timeline" aria-labelledby="timeline-title">
      <h1 id="timeline-title">{t("timeline.title")}</h1>
      <div className="timeline-filters">
        <label>
          {t("timeline.filter.date")}
          <input
            type="search"
            value={dateFilter}
            onChange={(event) => setDateFilter(event.target.value)}
          />
        </label>
        <label>
          {t("timeline.filter.person")}
          <select
            value={personFilter}
            onChange={(event) => setPersonFilter(event.target.value)}
          >
            <option value="">{t("timeline.filter.all")}</option>
            {people.map((person) => (
              <option key={person} value={person}>
                {t(`timeline.person.${person}`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("timeline.filter.evidence")}
          <select
            value={evidenceFilter}
            onChange={(event) => setEvidenceFilter(event.target.value)}
          >
            <option value="">{t("timeline.filter.all")}</option>
            {evidenceIds.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
      </div>
      {rows.length === 0 ? (
        <StateBlock
          locale={locale}
          kind="empty"
          message={t("timeline.empty")}
        />
      ) : (
        <ol className="timeline-list">
          {rows.map((row) => (
            <TimelineItem key={row.id} locale={locale} caseId={caseId} event={row} />
          ))}
        </ol>
      )}
    </section>
  );
}
