// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createAdapter } from "../adapter";
import type { IngestResult } from "../adapter";
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

    finish({ ok: true, value: { id: "E-TEST", hash: "abc123", duplicate: false } });
    expect(await screen.findByText(/E-TEST/)).toBeTruthy();
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

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Upload failed at Scanned",
    );
  });
});
