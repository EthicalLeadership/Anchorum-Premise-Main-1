import { translate } from "../i18n";
import type { Locale } from "../types";

export interface CaseFilters {
  status: string;
  owner: string;
}

interface FilterBarProps {
  locale: Locale;
  filters: CaseFilters;
  statuses: string[];
  owners: string[];
  onChange: (filters: CaseFilters) => void;
}

export function FilterBar({ locale, filters, statuses, owners, onChange }: FilterBarProps) {
  const all = "";
  return (
    <div className="filter-bar" role="group" aria-label={translate(locale, "case.list.title")}>
      <label>
        {translate(locale, "case.list.filter.status")}
        <select
          value={filters.status}
          onChange={(e) => onChange({ ...filters, status: e.target.value })}
        >
          <option value={all}></option>
          {statuses.map((s) => (
            <option key={s} value={s}>
              {translate(locale, `case.header.status.${s}` as never)}
            </option>
          ))}
        </select>
      </label>
      <label>
        {translate(locale, "case.list.filter.owner")}
        <select
          value={filters.owner}
          onChange={(e) => onChange({ ...filters, owner: e.target.value })}
        >
          <option value={all}></option>
          {owners.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
