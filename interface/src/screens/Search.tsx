import { useState, type FormEvent } from "react";
import type { createAdapter } from "../adapter";
import { StateBlock } from "../components/StateBlock";
import { translate } from "../i18n";
import type { Locale } from "../types";

type Props = { locale: Locale; adapter: ReturnType<typeof createAdapter>; caseId: string };
type Hit = { id: string; excerpt: string; offset?: number };
type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "building" }
  | { kind: "error"; key: string }
  | { kind: "ready"; hits: readonly Hit[] };

export function Search({ locale, adapter, caseId }: Props) {
  const [q, setQ] = useState("");
  const [state, setState] = useState<State>({ kind: "idle" });
  const t = (k: string, p?: Record<string, string>) => translate(locale, k as never, p as never);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    setState({ kind: "loading" });
    const r = await adapter.search.query(caseId, q);
    if (r.ok) setState({ kind: "ready", hits: r.value });
    else if (r.error === "INDEX_BUILDING") setState({ kind: "building" });
    else if (r.error === "BACKEND_UNREACHABLE") {
      setState({ kind: "error", key: "search.unavailable" });
    } else setState({ kind: "error", key: `error.${r.error.toLowerCase()}` });
  }

  return (
    <section className="search" aria-labelledby="search-title">
      <h1 id="search-title">{t("search.title")}</h1>
      <form role="search" aria-label={t("search.title")} onSubmit={submit} noValidate>
        <input
          type="search"
          value={q}
          placeholder={t("search.placeholder")}
          aria-label={t("search.placeholder")}
          onChange={(e) => setQ(e.target.value)}
        />
        <button type="submit" className="btn btn--primary">{t("search.title")}</button>
      </form>
      {state.kind === "loading" ? <StateBlock locale={locale} kind="loading" /> : null}
      {state.kind === "building" ? <p role="status">{t("search.index_building")}</p> : null}
      {state.kind === "error" ? <StateBlock locale={locale} kind="error" message={t(state.key)} /> : null}
      {state.kind === "ready" && state.hits.length === 0 ? <StateBlock locale={locale} kind="empty" message={t("search.no_results")} /> : null}
      {state.kind === "ready" && state.hits.length > 0 ? (
        <ul className="search-results">
          {state.hits.map((h) => (
            <li key={h.id}>
              <a href={`#/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(h.id)}`}>
                {h.id}
              </a>
              {h.offset !== undefined ? (
                <p className="search-result-location">
                  {t("search.result.location", {
                    evidenceId: h.id,
                    pageOrOffset: t("search.result.offset", { offset: String(h.offset) }),
                  })}
                </p>
              ) : null}
              <p>{h.excerpt}</p>
              <a href={`#/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(h.id)}`}>
                {t("search.result.open_exact")}
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
