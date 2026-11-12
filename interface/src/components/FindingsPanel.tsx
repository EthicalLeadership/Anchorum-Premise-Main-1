import { useEffect, useState } from "react";
import type { createAdapter } from "../adapter";
import type { Finding } from "../types";

type Props = {
  caseId: string;
  adapter: Pick<ReturnType<typeof createAdapter>, "board">;
};

export function FindingsPanel({ caseId, adapter }: Props) {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    adapter.board.findings(caseId).then((res) => {
      if (!active) return;
      if (res.ok) {
        setFindings(res.value);
        setError(null);
      } else {
        setError(res.error);
      }
      setLoading(false);
    });
    return () => { active = false; };
  }, [caseId, adapter]);

  async function updateStatus(id: string, newStatus: string) {
    const res = await adapter.board.updateFinding(caseId, id, newStatus);
    if (res.ok) {
      setFindings((prev) =>
        prev.map((f) => (f.id === id ? { ...f, status: newStatus as any } : f))
      );
    }
  }

  if (loading) return <div style={{ padding: '1rem', border: '1px solid #e5e7eb', borderRadius: '8px' }}>Loading findings...</div>;
  if (error) return <div style={{ padding: '1rem', border: '1px solid #e5e7eb', borderRadius: '8px', color: 'red' }}>Error: {error}</div>;

  return (
    <article style={{ background: '#fff', padding: '1.5rem', border: '1px solid #e5e7eb', borderRadius: '8px', marginBottom: '2rem' }}>
      <h2 style={{ fontSize: '1.25rem', fontWeight: 'bold', borderBottom: '1px solid #e5e7eb', paddingBottom: '0.5rem', marginBottom: '1rem' }}>
        Findings
      </h2>
      
      {findings.length === 0 ? (
        <p style={{ color: '#6b7280', fontStyle: 'italic' }}>No findings detected.</p>
      ) : (
        <ul style={{ padding: 0, margin: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {findings.map((f) => (
            <li key={f.id} style={{ padding: '1rem', border: '1px solid #e5e7eb', borderRadius: '6px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <strong style={{ display: 'block', fontSize: '0.9rem', color: '#b45309' }}>{f.title}</strong>
                  <span style={{ fontSize: '0.875rem', color: '#374151' }}>{f.rationale}</span>
                </div>
                <span style={{
                  fontSize: '0.75rem',
                  padding: '2px 8px',
                  borderRadius: '999px',
                  backgroundColor: f.status === 'confirmed' ? '#fecaca' : f.status === 'dismissed' ? '#e5e7eb' : '#fef3c7',
                  color: f.status === 'confirmed' ? '#991b1b' : f.status === 'dismissed' ? '#4b5563' : '#92400e',
                }}>
                  {f.status}
                </span>
              </div>

              <div style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
                <button type="button" onClick={() => updateStatus(f.id, 'confirmed')} style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem', cursor: 'pointer' }}>Confirm</button>
                <button type="button" onClick={() => updateStatus(f.id, 'dismissed')} style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem', cursor: 'pointer' }}>Dismiss</button>
                <button type="button" onClick={() => updateStatus(f.id, 'candidate')} style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem', cursor: 'pointer' }}>Reset</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}
