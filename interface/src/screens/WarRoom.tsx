import { useEffect, useState } from "react";
import { StateBlock } from "../components/StateBlock";
import { translate } from "../i18n";

type ChronologyEntry = {
  message_id: string;
  date: string | null;
  date_raw: string | null;
  from_address: string | null;
  to_address: string | null;
  subject: string | null;
  thread_id: string | null;
};

type ChronologyResponse = {
  case_id: string;
  total_dated: number;
  total_undated: number;
  truncated: boolean;
  dated_entries: ChronologyEntry[];
  undated_tray: ChronologyEntry[];
};

type CommEdge = {
  from_address: string;
  to_address: string;
  count: number;
};

type ActorsResponse = {
  case_id: string;
  total_messages: number;
  unique_actors: number;
  edges: CommEdge[];
};

type GapItem = {
  id: string;
  description: string;
  status: string;
  referenced_in_message_id: string | null;
};

type GapResponse = {
  case_id: string;
  total: number;
  gaps: GapItem[];
};

type BoardData = {
  chronology: ChronologyResponse;
  actors: ActorsResponse;
  gaps: GapResponse;
};

function apiBase(): string {
  const env = import.meta.env as { VITE_API_BASE_URL?: string };
  return env.VITE_API_BASE_URL?.trim() ?? "";
}

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export function WarRoom({ caseId, locale }: { caseId: string; locale: "en" | "fr" }) {
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "ready"; data: BoardData }
    | { kind: "error" }
  >({ kind: "loading" });

  useEffect(() => {
    let live = true;
    setState({ kind: "loading" });
    Promise.all([
      fetchJson<ChronologyResponse>(`/board/${caseId}/chronology`),
      fetchJson<ActorsResponse>(`/board/${caseId}/actors`),
      fetchJson<GapResponse>(`/board/${caseId}/gaps`),
    ])
      .then(([chronology, actors, gaps]) => {
        if (!live) return;
        setState({ kind: "ready", data: { chronology, actors, gaps } });
      })
      .catch(() => {
        if (!live) return;
        setState({ kind: "error" });
      });
    return () => {
      live = false;
    };
  }, [caseId]);

  if (state.kind === "loading") {
    return (
      <section className="war-room" data-testid="war-room">
        <StateBlock locale={locale} kind="loading" />
      </section>
    );
  }
  if (state.kind === "error") {
    return (
      <section className="war-room" data-testid="war-room">
        <StateBlock locale={locale} kind="error" />
      </section>
    );
  }

  const { chronology, actors, gaps } = state.data;

  return (
    <section className="war-room" data-testid="war-room">
      <header className="war-room__header">
        <h1>{translate(locale, "warroom.title")}</h1>
        {chronology.truncated && (
          <p className="war-room__warning" role="alert">
            {translate(locale, "warroom.truncated")}
          </p>
        )}
      </header>

      <div className="war-room__grid">
        <article
          className="war-room__chronology"
          data-testid="war-room-chronology"
        >
          <h2>{translate(locale, "warroom.chronology.title")}</h2>
          <ol>
            {chronology.dated_entries.map((entry) => (
              <li key={entry.message_id}>
                <time>{entry.date ?? ""}</time>
                <span>
                  {entry.from_address ?? "\u2014"} &rarr;{" "}
                  {entry.to_address ?? "\u2014"}
                </span>
                <span>{entry.subject ?? ""}</span>
              </li>
            ))}
          </ol>
          {chronology.undated_tray.length > 0 && (
            <section
              className="war-room__undated"
              data-testid="war-room-undated"
            >
              <h3>{translate(locale, "warroom.undated.title")}</h3>
              <ul>
                {chronology.undated_tray.map((entry) => (
                  <li key={entry.message_id}>
                    <span>{entry.date_raw ?? "\u2014"}</span>
                    <span>
                      {entry.from_address ?? "\u2014"} &rarr;{" "}
                      {entry.to_address ?? "\u2014"}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </article>

        <article className="war-room__gaps" data-testid="war-room-gaps">
          <h2>{translate(locale, "warroom.gaps.title")}</h2>
          {gaps.gaps.length === 0 ? (
            <p>{translate(locale, "warroom.gaps.empty")}</p>
          ) : (
            <ul>
              {gaps.gaps.map((gap) => (
                <li key={gap.id}>
                  <strong>{gap.status}</strong> &mdash; {gap.description}
                </li>
              ))}
            </ul>
          )}
        </article>

        <article className="war-room__actors" data-testid="war-room-actors">
          <h2>{translate(locale, "warroom.actors.title")}</h2>
          <table>
            <thead>
              <tr>
                <th>{translate(locale, "warroom.actors.from")}</th>
                <th>{translate(locale, "warroom.actors.to")}</th>
                <th>{translate(locale, "warroom.actors.count")}</th>
              </tr>
            </thead>
            <tbody>
              {actors.edges.map((edge, i) => (
                <tr key={`${edge.from_address}-${edge.to_address}-${i}`}>
                  <td>{edge.from_address}</td>
                  <td>{edge.to_address}</td>
                  <td>{edge.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </article>
      </div>
    </section>
  );
}
