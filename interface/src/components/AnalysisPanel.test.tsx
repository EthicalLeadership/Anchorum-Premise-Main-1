import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { AnalysisPanel } from "./AnalysisPanel";
import type { AnalysisRecord } from "../types";

const baseRecord: AnalysisRecord = {
  id: "E-1", status: "processed", reason: "",
  source: { sha256: "a".repeat(64), bytes: 149819, mediaType: "application/pdf", filename: "brief.pdf" },
  extract: { status: "extracted", chars: 4845, sha256: "b".repeat(64), error: "" },
  projection: { engineVersion: "ccsp-3.3.0", lexiconHash: "c".repeat(64), configHash: "d".repeat(64) },
  coverage: { scopesTotal: 8, scopesMatched: 1, scopesFallback: 7, scopesInsufficient: 0, ratio: 0.125, warning: "lexicon covered 1 of 8 scopes" },
  scopes: [
    { scope: "FACTS", chars: 2009, conceptId: "LEGAL_ALLEGATION", classification: "canonical_projection_insufficient", admissible: false, matchedConcepts: ["LEGAL_ALLEGATION"], fallbackReason: null },
  ],
};

function makeAdapter(record: AnalysisRecord = baseRecord) {
  return { evidence: {
    analysis: vi.fn().mockResolvedValue({ ok: true, value: record }),
    analyse: vi.fn().mockResolvedValue({ ok: true, value: record }),
  } } as any;
}

describe("AnalysisPanel", () => {
  it("fetches once on mount and renders scope rows", async () => {
    const adapter = makeAdapter();
    render(<AnalysisPanel evidenceId="E-1" adapter={adapter} />);
    await waitFor(() => expect(screen.getByText(/FACTS/)).toBeInTheDocument());
    expect(adapter.evidence.analysis).toHaveBeenCalledWith("E-1");
    expect(adapter.evidence.analysis).toHaveBeenCalledTimes(1);
  });

  it("re-fetches when evidenceId changes", async () => {
    const adapter = makeAdapter();
    const { rerender } = render(<AnalysisPanel evidenceId="E-1" adapter={adapter} />);
    await waitFor(() => expect(screen.getByText(/FACTS/)).toBeInTheDocument());
    const rec2: AnalysisRecord = { ...baseRecord, scopes: [{ ...baseRecord.scopes[0], scope: "ISSUE" }] };
    adapter.evidence.analysis.mockResolvedValueOnce({ ok: true, value: rec2 });
    rerender(<AnalysisPanel evidenceId="E-2" adapter={adapter} />);
    await waitFor(() => expect(screen.getByText(/ISSUE/)).toBeInTheDocument());
    expect(adapter.evidence.analysis).toHaveBeenCalledWith("E-2");
  });

  it("renders coverage warning as alert", async () => {
    render(<AnalysisPanel evidenceId="E-1" adapter={makeAdapter()} />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("lexicon covered 1 of 8 scopes");
  });

  it("renders unsupported distinctly", async () => {
    const rec: AnalysisRecord = { ...baseRecord, status: "unsupported", reason: "docx not supported", scopes: [] };
    render(<AnalysisPanel evidenceId="E-1" adapter={makeAdapter(rec)} />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Unsupported");
    expect(alert.textContent).toContain("docx not supported");
    expect(screen.queryByText("Scopes")).not.toBeInTheDocument();
  });

  it("renders failed with reason", async () => {
    const rec: AnalysisRecord = { ...baseRecord, status: "failed", reason: "PdfTextError: no text layer", scopes: [] };
    render(<AnalysisPanel evidenceId="E-1" adapter={makeAdapter(rec)} />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Analysis failed");
    expect(alert.textContent).toContain("no text layer");
  });

  it("renders skipped_oversize with ceiling", async () => {
    const rec: AnalysisRecord = { ...baseRecord, status: "skipped_oversize", reason: "artifact is 30000000 bytes, above the 26214400 byte ceiling", scopes: [] };
    render(<AnalysisPanel evidenceId="E-1" adapter={makeAdapter(rec)} />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("too large");
    expect(alert.textContent).toContain("26214400");
  });

  it("renders empty distinctly", async () => {
    const rec: AnalysisRecord = { ...baseRecord, status: "empty", reason: "", scopes: [] };
    render(<AnalysisPanel evidenceId="E-1" adapter={makeAdapter(rec)} />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("No text was extracted");
    expect(alert.textContent).toContain("scan without a text layer");
  });

  it("renders pending as neutral", async () => {
    const rec: AnalysisRecord = { ...baseRecord, status: "pending", scopes: [] };
    render(<AnalysisPanel evidenceId="E-1" adapter={makeAdapter(rec)} />);
    expect(await screen.findByText(/has not run on this item yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders unknown status with raw code", async () => {
    const rec: AnalysisRecord = { ...baseRecord, status: "weird_status", scopes: [] };
    render(<AnalysisPanel evidenceId="E-1" adapter={makeAdapter(rec)} />);
    expect(await screen.findByText(/Unknown analysis status/i)).toBeInTheDocument();
    expect(screen.getByText("weird_status")).toBeInTheDocument();
  });

  it("re-analyse updates from POST response", async () => {
    const adapter = makeAdapter();
    const updated: AnalysisRecord = { ...baseRecord, coverage: { ...baseRecord.coverage, scopesMatched: 2 } };
    adapter.evidence.analyse.mockResolvedValueOnce({ ok: true, value: updated });
    render(<AnalysisPanel evidenceId="E-1" adapter={adapter} />);
    await waitFor(() => expect(screen.getByText(/FACTS/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /re-analyse/i }));
    await waitFor(() => expect(adapter.evidence.analyse).toHaveBeenCalledWith("E-1"));
    await waitFor(() => expect(screen.getByText(/2 of 8 scopes matched/)).toBeInTheDocument());
  });

  it("error state and Retry re-fetches", async () => {
    const adapter = makeAdapter();
    adapter.evidence.analysis
      .mockResolvedValueOnce({ ok: false, error: "network down" })
      .mockResolvedValueOnce({ ok: true, value: baseRecord });
    render(<AnalysisPanel evidenceId="E-1" adapter={adapter} />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("network down");
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(screen.getByText(/FACTS/)).toBeInTheDocument());
    expect(adapter.evidence.analysis).toHaveBeenCalledTimes(2);
  });
});