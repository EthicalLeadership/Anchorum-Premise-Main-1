import { useEffect, useState } from "react";
import type { createAdapter } from "../adapter";
import { StateBlock } from "../components/StateBlock";
import { FindingsPanel } from "../components/FindingsPanel";
import { translate } from "../i18n";
import type { Locale, ChronologyEntry, CommEdge, GapItem } from "../types";

type Props = {
  locale: Locale;
  // FIX: Only require the board methods, not the entire adapter
  adapter: Pick<ReturnType<typeof createAdapter>, "board">;
  caseId: string;
};

type BoardData = {
  chronology: any;
  actors: any;
  gaps: any;
};

export function WarRoom({ caseId, locale, adapter }: Props) {
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "ready"; data: BoardData }
    | { kind: "error" }
  >({ kind: "loading" });

  const [anchorStatus, setAnchorStatus] = useState<string | null>(null);
  const [anchorLoading, setAnchorLoading] = useState(false);

  useEffect(() => {
    let active = true;
    setState({ kind: "loading" });

    (async () => {
      try {
        const chronoRes = await adapter.board.chronology(caseId);
        const actorsRes = await adapter.board.actors(caseId);
        const gapsRes = await adapter.board.gaps(caseId);

        if (!active) return;

        if (!chronoRes.ok || !actorsRes.ok || !gapsRes.ok) {
          setState({ kind: "error" });
          return;
        }

        setState({
          kind: "ready",
          data: {
            chronology: chronoRes.value,
            actors: actorsRes.value,
            gaps: gapsRes.value,
          },
        });
      } catch (err) {
        if (active) setState({ kind: "error" });
      }
    })();

    return () => { active = false; };
  }, [caseId, adapter]);

  if (state.kind === "loading") {
    return (
      <section style={{ padding: '2rem' }} data-testid="war-room">
        <StateBlock locale={locale} kind="loading" />
      </section>
    );
  }

  if (state.kind === "error") {
    return (
      <section style={{ padding: '2rem' }} data-testid="war-room">
        <StateBlock locale={locale} kind="error" />
      </section>
    );
  }

  const { chronology, actors, gaps } = state.data;

  return (
    <section style={{ padding: '2rem', maxWidth: '1200px', margin: '0 auto' }} data-testid="war-room">
      <header style={{ marginBottom: '2rem' }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <h1 style={{ fontSize: "2rem", fontWeight: "bold", margin: 0 }}>{translate(locale, "warroom.title")}</h1>
          <div className="card" style={{ padding: "12px 20px", display: "flex", alignItems: "center", gap: "16px" }}>
            <div>
              <h3 style={{ margin: 0, fontSize: "11px", color: "var(--text-muted)", letterSpacing: "0.08em" }}>BITCOIN INTEGRITY PROOF</h3>
              <p style={{ margin: "4px 0 0 0", fontSize: "13px", fontFamily: "var(--font-sans)" }}>
                {anchorStatus ? anchorStatus : "Not yet anchored"}
              </p>
            </div>
            <button
              type="button"
              className="btn btn--primary"
              disabled={anchorLoading}
              onClick={async () => {
                setAnchorLoading(true);
                try {
                  const res = await fetch(`/ledger/snapshots/${encodeURIComponent(caseId)}/anchor`, { method: "POST" });
                  if (res.ok) {
                    setAnchorStatus("Pending confirmation");
                  } else {
                    const err = await res.json().catch(() => ({}));
                    setAnchorStatus(err.detail || `Failed (${res.status})`);
                  }
                } catch {
                  setAnchorStatus("Error: backend unreachable");
                } finally {
                  setAnchorLoading(false);
                }
              }}
            >
              {anchorLoading ? "Stamping..." : "Anchor to Bitcoin"}
            </button>
          </div>
        </div>
        {chronology.truncated && (
          <p style={{ color: '#b45309', background: '#fef3c7', padding: '0.5rem', borderRadius: '4px', marginTop: '1rem' }} role="alert">
            {translate(locale, "warroom.truncated")}
          </p>
        )}
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '1rem', marginBottom: '2rem' }}>
        <div style={{ padding: '1.5rem', border: '1px solid #e5e7eb', borderRadius: '8px', background: '#fff' }}>
          <h3 style={{ fontSize: '0.875rem', color: '#6b7280', textTransform: 'uppercase' }}>Total Messages</h3>
          <p style={{ fontSize: '2rem', fontWeight: 'bold', margin: 0 }}>{actors.total_messages}</p>
        </div>
        <div style={{ padding: '1.5rem', border: '1px solid #e5e7eb', borderRadius: '8px', background: '#fff' }}>
          <h3 style={{ fontSize: '0.875rem', color: '#6b7280', textTransform: 'uppercase' }}>Unique Actors</h3>
          <p style={{ fontSize: '2rem', fontWeight: 'bold', margin: 0 }}>{actors.unique_actors}</p>
        </div>
        <div style={{ padding: '1.5rem', border: '1px solid #e5e7eb', borderRadius: '8px', background: '#fff' }}>
          <h3 style={{ fontSize: '0.875rem', color: '#6b7280', textTransform: 'uppercase' }}>Open Gaps</h3>
          <p style={{ fontSize: '2rem', fontWeight: 'bold', margin: 0 }}>{gaps.total}</p>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '2rem' }}>
        <article style={{ background: '#fff', padding: '1.5rem', border: '1px solid #e5e7eb', borderRadius: '8px' }} data-testid="war-room-chronology">
          <h2 style={{ fontSize: '1.25rem', fontWeight: 'bold', borderBottom: '1px solid #e5e7eb', paddingBottom: '0.5rem', marginBottom: '1rem' }}>
            {translate(locale, "warroom.chronology.title")}
          </h2>
          <ol style={{ paddingLeft: '1.5rem', margin: 0 }}>
            {chronology.dated_entries.map((entry: ChronologyEntry) => (
              <li key={entry.message_id} style={{ marginBottom: '1rem' }}>
                <time style={{ color: '#6b7280', fontSize: '0.875rem', display: 'block' }}>{entry.date ?? ""}</time>
                <span style={{ fontWeight: '500' }}>{entry.from_address ?? "\u2014"} &rarr; {entry.to_address ?? "\u2014"}</span>
                <span style={{ display: 'block', color: '#374151' }}>{entry.subject ?? ""}</span>
              </li>
            ))}
          </ol>
          {chronology.undated_tray.length > 0 && (
            <section data-testid="war-room-undated" style={{ marginTop: '2rem' }}>
              <h3 style={{ fontSize: '1rem', marginBottom: '0.5rem' }}>
                {translate(locale, "warroom.undated.title")}
              </h3>
              <ul style={{ paddingLeft: '1.5rem', margin: 0 }}>
                {chronology.undated_tray.map((entry: ChronologyEntry) => (
                  <li key={entry.message_id} style={{ marginBottom: '0.5rem' }}>
                    <span style={{ color: '#6b7280', fontSize: '0.875rem' }}>
                      {entry.date_raw ?? "\u2014"}
                    </span>
                    {" — "}
                    <span>{entry.from_address ?? "\u2014"} &rarr; {entry.to_address ?? "\u2014"}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </article>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
          <FindingsPanel adapter={adapter} caseId={caseId} />
          
          <article style={{ background: '#fff', padding: '1.5rem', border: '1px solid #e5e7eb', borderRadius: '8px' }} data-testid="war-room-gaps">
            <h2 style={{ fontSize: '1.25rem', fontWeight: 'bold', borderBottom: '1px solid #e5e7eb', paddingBottom: '0.5rem', marginBottom: '1rem' }}>
              {translate(locale, "warroom.gaps.title")}
            </h2>
            {gaps.gaps.length === 0 ? (
              <p style={{ color: '#6b7280', fontStyle: 'italic' }}>{translate(locale, "warroom.gaps.empty")}</p>
            ) : (
              <ul style={{ paddingLeft: '1.5rem', margin: 0 }}>
                {gaps.gaps.map((gap: GapItem) => (
                  <li key={gap.id} style={{ marginBottom: '0.75rem' }}>
                    <strong style={{ color: '#b45309', fontSize: '0.75rem', textTransform: 'uppercase' }}>{gap.status}</strong>
                    <span style={{ display: 'block' }}><><strong>[{gap.severity}]</strong> {gap.description}</></span>
                  </li>
                ))}
              </ul>
            )}
          </article>

          <article style={{ background: '#fff', padding: '1.5rem', border: '1px solid #e5e7eb', borderRadius: '8px' }} data-testid="war-room-actors">
            <h2 style={{ fontSize: '1.25rem', fontWeight: 'bold', borderBottom: '1px solid #e5e7eb', paddingBottom: '0.5rem', marginBottom: '1rem' }}>
              {translate(locale, "warroom.actors.title")}
            </h2>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #e5e7eb', textAlign: 'left' }}>
                  <th style={{ paddingBottom: '0.5rem' }}>{translate(locale, "warroom.actors.from")}</th>
                  <th style={{ paddingBottom: '0.5rem' }}>{translate(locale, "warroom.actors.to")}</th>
                  <th style={{ paddingBottom: '0.5rem' }}>{translate(locale, "warroom.actors.count")}</th>
                </tr>
              </thead>
              <tbody>
                {actors.edges.map((edge: CommEdge, i: number) => (
                  <tr key={`${edge.from_address}-${edge.to_address}-${i}`} style={{ borderBottom: '1px solid #f3f4f6' }}>
                    <td style={{ padding: '0.5rem 0' }}>{edge.from_address}</td>
                    <td style={{ padding: '0.5rem 0' }}>{edge.to_address}</td>
                    <td style={{ padding: '0.5rem 0' }}>{edge.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </article>
        </div>
      </div>
    </section>
  );
}