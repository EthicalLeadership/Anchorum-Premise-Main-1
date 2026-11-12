/**
 * The Analysis tab body: fetch the full analysis record for one evidence item
 * and render every status distinctly. Each of unsupported / empty /
 * skipped_oversize / failed means "we could not read this document", with a
 * different reason a reader needs to see; collapsing them hides that
 * difference. English-only for now; i18n deferred, matching FindingsPanel.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { createAdapter } from "../adapter";
import type { AnalysisRecord } from "../types";

type Props = {
  evidenceId: string;
  adapter: Pick<ReturnType<typeof createAdapter>, "evidence">;
};

type Load =
  | { kind: "loading" }
  | { kind: "ready"; record: AnalysisRecord }
  | { kind: "error"; message: string };

export function AnalysisPanel({ evidenceId, adapter }: Props) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [rerunning, setRerunning] = useState(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const fetchRecord = useCallback(async () => {
    setLoad({ kind: "loading" });
    try {
      const res = await adapter.evidence.analysis(evidenceId);
      if (!alive.current) return;
      if (res.ok) setLoad({ kind: "ready", record: res.value });
      else setLoad({ kind: "error", message: res.error });
    } catch (e) {
      if (!alive.current) return;
      setLoad({ kind: "error", message: e instanceof Error ? e.message : String(e) });
    }
  }, [adapter, evidenceId]);

  useEffect(() => {
    void fetchRecord();
  }, [fetchRecord]);

  const rerun = useCallback(async () => {
    setRerunning(true);
    try {
      const res = await adapter.evidence.analyse(evidenceId);
      if (!alive.current) return;
      if (res.ok) setLoad({ kind: "ready", record: res.value });
      else setLoad({ kind: "error", message: res.error });
    } catch (e) {
      if (!alive.current) return;
      setLoad({ kind: "error", message: e instanceof Error ? e.message : String(e) });
    } finally {
      if (alive.current) setRerunning(false);
    }
  }, [adapter, evidenceId]);

  if (load.kind === "loading") {
    return (
      <section className="analysis-panel" aria-busy="true">
        <p>Loading analysis{"\u2026"}</p>
      </section>
    );
  }

  if (load.kind === "error") {
    return (
      <section className="analysis-panel">
        <div role="alert">
          <p><strong>Analysis unavailable:</strong> {load.message}</p>
          <button type="button" onClick={() => void fetchRecord()}>Retry</button>
        </div>
      </section>
    );
  }

  return (
    <section className="analysis-panel" aria-labelledby="analysis-heading">
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "1rem" }}>
        <h2 id="analysis-heading" style={{ margin: 0, fontSize: "1.25rem" }}>Analysis</h2>
        <button type="button" onClick={() => void rerun()} disabled={rerunning}>
          {rerunning ? "Re-analysing\u2026" : "Re-analyse"}
        </button>
      </header>
      <StatusBlock record={load.record} />
    </section>
  );
}

function StatusBlock({ record }: { record: AnalysisRecord }) {
  switch (record.status) {
    case "processed":
      return <ProcessedView record={record} />;
    case "unsupported":
      return (
        <div role="alert">
          <p><strong>Unsupported artifact type.</strong></p>
          <p>{record.reason}</p>
        </div>
      );
    case "empty":
      return (
        <div role="alert">
          <p><strong>No text was extracted.</strong></p>
          <p>{record.reason || "The artifact may be a scan without a text layer, or empty."}</p>
        </div>
      );
    case "skipped_oversize":
      return (
        <div role="alert">
          <p><strong>Artifact too large to analyse.</strong></p>
          <p>{record.reason}</p>
        </div>
      );
    case "failed":
      return (
        <div role="alert">
          <p><strong>Analysis failed.</strong></p>
          <p>{record.reason}</p>
        </div>
      );
    case "pending":
      return <p>Analysis has not run on this item yet.</p>;
    default:
      return (
        <p>
          <strong>Unknown analysis status:</strong> <code>{record.status}</code>
          {record.reason ? ` \u2014 ${record.reason}` : ""}
        </p>
      );
  }
}

function ProcessedView({ record }: { record: AnalysisRecord }) {
  const { coverage, extract, projection, scopes, source } = record;
  const hasWarning = coverage.warning !== null && coverage.warning.trim() !== "";

  return (
    <>
      {hasWarning && (
        <div role="alert">
          <p><strong>Lexicon coverage warning:</strong> {coverage.warning}</p>
        </div>
      )}
      <dl>
        <dt>Source</dt>
        <dd>
          <code>{source.filename || "(no filename)"}</code>{" \u00b7 "}
          {source.bytes} bytes{" \u00b7 "}sha256{" "}
          <code>{source.sha256.slice(0, 16)}{"\u2026"}</code>
        </dd>
        <dt>Extract</dt>
        <dd>
          {extract.chars} chars{" \u00b7 "}sha256{" "}
          <code>{extract.sha256.slice(0, 16)}{"\u2026"}</code>
        </dd>
        <dt>Coverage</dt>
        <dd>
          {coverage.scopesMatched} of {coverage.scopesTotal} scopes matched{" \u00b7 "}
          {coverage.scopesFallback} fell back
        </dd>
        <dt>Projection</dt>
        <dd>
          {projection.engineVersion || "(unknown)"}{" \u00b7 "}lexicon{" "}
          <code>{projection.lexiconHash.slice(0, 16)}{"\u2026"}</code>
        </dd>
      </dl>
      <h3 style={{ marginTop: "1.5rem" }}>Scopes</h3>
      {scopes.length === 0 ? (
        <p>No scopes were segmented from the extracted text.</p>
      ) : (
        <ul>
          {scopes.map((s, i) => (
            <li key={`${s.scope}-${i}`} style={{ marginBottom: "0.5rem" }}>
              <strong>{s.scope}</strong>{" \u00b7 "}{s.chars} chars{" \u00b7 "}{s.classification}
              {s.matchedConcepts.length > 0 && (
                <>{" \u00b7 "}matched: {s.matchedConcepts.join(", ")}</>
              )}
              {s.fallbackReason !== null && s.fallbackReason !== "" && (
                <>{" \u00b7 "}{s.fallbackReason}</>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}