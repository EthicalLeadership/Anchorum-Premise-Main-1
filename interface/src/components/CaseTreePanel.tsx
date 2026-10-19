import { useEffect, useState } from "react";
import type { CaseRow, createAdapter } from "../adapter";
import { translate } from "../i18n";
import type { Locale } from "../types";
import type { MessageKey } from "../i18n";

const CATEGORIES = ["medical", "payroll", "correspondence", "pleading", "other"] as const;
const SOURCES = ["clinic", "insurer", "employer", "court", "other"] as const;

type Props = {
  locale: Locale;
  adapter: ReturnType<typeof createAdapter>;
};

export function CaseTreePanel({ locale, adapter }: Props) {
  const t = (k: MessageKey) => translate(locale, k);
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState<string>("");
  const [source, setSource] = useState<string>("");
  const [uploading, setUploading] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const refresh = async () => {
    const r = await adapter.cases.list();
    if (r.ok) setCases([...r.value]);
  };

  useEffect(() => {
    void refresh().finally(() => setLoading(false));
  }, []);

  const onFile = async (caseId: string, file: File) => {
    setUploading(caseId);
    setErrors((e) => {
      const next = { ...e };
      delete next[caseId];
      return next;
    });
    try {
      const bytes = await file.arrayBuffer();
      const r = await adapter.evidence.ingest(caseId, {
        name: file.name,
        size: file.size,
        type: file.type || "",
        bytes,
        category: category || null,
        source: source || null,
      });
      if (!r.ok) {
        setErrors((e) => ({ ...e, [caseId]: String(r.error ?? "unknown") }));
      } else {
        await refresh();
      }
    } catch (err) {
      setErrors((e) => ({
        ...e,
        [caseId]: err instanceof Error ? err.message : String(err),
      }));
    } finally {
      setUploading(null);
    }
  };

  return (
    <div className="case-tree">
      <h2 className="case-tree__title">{t("case.tree.title")}</h2>
      <div className="case-tree__filters">
        <label>
          {t("evidence.intake.category")}
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">{t("case.tree.unset")}</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {t(`evidence.category.${c}` as MessageKey)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("evidence.intake.source")}
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">{t("case.tree.unset")}</option>
            {SOURCES.map((s) => (
              <option key={s} value={s}>
                {t(`evidence.source.${s}` as MessageKey)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {loading ? (
        <p>{t("state.loading")}</p>
      ) : cases.length === 0 ? (
        <p>{t("case.tree.empty")}</p>
      ) : (
        <ul className="case-tree__list">
          {cases.map((c) => (
            <li key={c.id} className="case-tree__row">
              <div className="case-tree__meta">
                <strong>{c.key}</strong>
                <span>{c.title}</span>
                <span className="case-tree__count">{c.evidenceCount}</span>
              </div>
              {uploading === c.id ? (
                <span className="case-tree__uploading">{t("case.tree.uploading")}</span>
              ) : (
                <label className="case-tree__upload">
                  {t("case.tree.upload")}
                  <input
                    type="file"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) void onFile(c.id, f);
                      e.target.value = "";
                    }}
                  />
                </label>
              )}
              {errors[c.id] ? (
                <p className="case-tree__error">{errors[c.id]}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
