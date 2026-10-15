// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createAdapter } from "../adapter";
import type { EvidenceAnalysis, ExtractStatus, IngestResult } from "../adapter";
import { EvidenceIntake } from "./EvidenceIntake";

afterEach(cleanup);

describe("EvidenceIntake", () => {
  function uploadFile() {
    const file = new File(["hello"], "a.pdf", { type: "application/pdf" });
    Object.defineProperty(file, "arrayBuffer", {
      value: async () => new TextEncoder().encode("hello").buffer,
    });
    fireEvent.change(screen.getByTestId("file-input"), { target: { files: [file] } });
  }

  function accepted(
    processingStatus: ExtractStatus,
    analysis: EvidenceAnalysis | null = null,
  ) {
    const adapter = createAdapter({ backend: null });
    vi.spyOn(adapter.evidence, "ingest").mockResolvedValue({
      ok: true,
      value: {
        id: "E-STATUS",
        hash: "abc123",
        sourceSha256: "abc123",
        duplicate: false,
        processingStatus,
        analysis,
      },
    });
    render(<EvidenceIntake locale="en" adapter={adapter} caseId="CASE-2024-018" />);
    uploadFile();
    return adapter;
  }

  it("ingests a file and shows a result row", async () => {
    const adapter = createAdapter({ backend: null });
    render(<EvidenceIntake locale="en" adapter={adapter} caseId="CASE-2024-018" />);
    uploadFile();
    expect(await screen.findByText("a.pdf")).toBeTruthy();
    expect(await screen.findByText(/E-1048/)).toBeTruthy();
  });

  it("shows per-file stage progress while ingestion is pending", async () => {
    const adapter = createAdapter({ backend: null });
    let finish: (result: IngestResult) => void = () => {};
    vi.spyOn(adapter.evidence, "ingest").mockImplementation(
      () => new Promise((resolve) => { finish = resolve; }),
    );
    render(<EvidenceIntake locale="en" adapter={adapter} caseId="CASE-2024-018" />);

    uploadFile();

    const progress = await screen.findByText("In progress");
    const progressStrip = progress.closest(".progress-strip");
    expect(progressStrip).toHaveAttribute("data-state", "active");
    expect(
      Array.from(progressStrip?.querySelectorAll("ol li") ?? [], (stage) =>
        stage.textContent,
      ),
    ).toEqual(["Received", "Preserved", "Scanned", "Indexed"]);

    finish({
      ok: true,
      value: {
        id: "E-TEST",
        hash: "abc123",
        sourceSha256: "abc123",
        duplicate: false,
      },
    });
    expect(await screen.findByText(/E-TEST/)).toBeTruthy();
  });

  it("reports an artifact that was read as done", async () => {
    accepted("extracted");
    expect(await screen.findByText("Done")).toBeTruthy();
  });

  it("reports a refused artifact type as failed, not as done", async () => {
    // The previous mapping was `processingStatus === "stored" ? "stored"
    // : "done"`, so this case rendered as "Done" — the opposite of what
    // happened: the connector has no reader for the file and never looked.
    accepted("unsupported");
    expect(await screen.findByText("Failed")).toBeTruthy();
    expect(screen.queryByText("Done")).toBeNull();
    expect(
      screen.getByText(
        "Not read: this connector has no reader for this file type.",
      ),
    ).toHaveAttribute("role", "alert");
  });

  it("keeps a stored artifact as stored rather than claiming it was read", async () => {
    accepted("stored");
    expect(
      await screen.findByText(
        "Stored locally; scanning and indexing are not performed.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText("Done")).toBeNull();
  });

  it("treats an unrecognised status as a failure rather than a success", async () => {
    accepted("who_knows" as ExtractStatus);
    expect(await screen.findByText("Failed")).toBeTruthy();
    expect(screen.queryByText("Done")).toBeNull();
  });

  it("surfaces the coverage warning the analysis reported", async () => {
    accepted("extracted", {
      status: "processed",
      scopesTotal: 8,
      scopesMatched: 1,
      warning: "the lexicon covered 1 of 8 scopes",
      analysedAt: "2026-05-01T10:00:00+00:00",
    });
    expect(
      await screen.findByText("Coverage: the lexicon covered 1 of 8 scopes"),
    ).toBeTruthy();
  });

  it("names a failed ingest stage returned by the adapter", async () => {
    const adapter = createAdapter({ backend: null });
    vi.spyOn(adapter.evidence, "ingest").mockResolvedValue({
      ok: false,
      error: "BACKEND_UNREACHABLE",
      failedStage: "scanned",
    });
    render(<EvidenceIntake locale="en" adapter={adapter} caseId="CASE-2024-018" />);

    uploadFile();

    expect(await screen.findByText("Upload failed at Scanned")).toHaveAttribute(
      "role",
      "alert",
    );
  });

  it("explains when the connected API does not implement evidence intake", async () => {
    const adapter = createAdapter({ backend: null });
    vi.spyOn(adapter.evidence, "ingest").mockResolvedValue({
      ok: false,
      error: "FEATURE_UNAVAILABLE",
    });
    render(<EvidenceIntake locale="en" adapter={adapter} caseId="CASE-2024-018" />);

    uploadFile();

    expect(await screen.findByText(
      "This feature is not available from the connected API yet.",
    )).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Browse cases" })).toHaveAttribute(
      "href",
      "#/cases",
    );
  });
});
