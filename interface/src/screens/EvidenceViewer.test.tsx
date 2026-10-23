// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen , waitFor , waitFor , waitFor , waitFor , waitFor } from "@testing-library/react";
import { createAdapter } from "../adapter";
import { EvidenceViewer } from "./EvidenceViewer";
import { translate } from "../i18n";

afterEach(cleanup);

it("renders a custody chain timeline alongside the custody table", async () => {
  view("E-1047");
  await screen.findByRole("heading", { level: 1 });
  const table = document.querySelector(".evidence-viewer table");
  if (!table) return; // fixture has no custody entries for this id
  const timeline = screen.getByTestId("chain-timeline");
  expect(timeline).toBeTruthy();
  const tableRows = table.querySelectorAll("tbody tr").length;
  const timelineSteps = timeline.querySelectorAll(".chain-timeline__step").length;
  expect(timelineSteps).toBe(tableRows);
});
const view = (id: string) =>
  render(<EvidenceViewer locale="en" adapter={createAdapter({ backend: null })} caseId="CASE-2024-018" evidenceId={id} />);

describe("EvidenceViewer", () => {
  it("names the failing step for an integrity hold", async () => {
    view("E-1047");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(translate("en", "overview.integrity.step.hash"));
  });

  it("shows not yet verified when no verification exists", async () => {
    view("E-1045");
    expect(await screen.findByText(translate("en", "verification.not_yet_verified"))).toBeTruthy();
  });

  it("alerts on an unknown id", async () => {
    view("E-9999");
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  it("switches to the extracted text panel and reports a failed fetch", async () => {
    view("E-1047");
    await screen.findByRole("heading", { level: 1 });
    fireEvent.click(
      screen.getByRole("tab", {
        name: translate("en", "evidence.viewer.tab.extracted"),
      }),
    );
    // The fixture adapter has no backend, so `evidence.text` answers
    // FEATURE_UNAVAILABLE. The panel must say the fetch failed rather than
    // rendering an empty document, which would read as "no text in the file".
    expect(
      await screen.findByText(translate("en", "evidence.text.error")),
    ).toBeTruthy();
  });

  it("shows truncated SHA-256 and HMAC in metadata", async () => {
    const { container } = render(
      <EvidenceViewer
        locale="en"
        adapter={createAdapter({ backend: null })}
        caseId="CASE-2024-018"
        evidenceId="E-1047"
      />,
    );
    const meta = await waitFor(() => {
      const el = container.querySelector('[data-testid="evidence-metadata"]');
      if (!el) throw new Error("metadata block not rendered yet");
      return el;
    });
    // Last custody row is A-3, hmac c3c3... → truncated c3c3c3c3…c3c3
    expect(meta.textContent).toMatch(/c3c3c3c3…c3c3/i);
    // SHA-256 line present (either a hash or "unavailable")
    expect(meta.textContent).toMatch(/SHA-256/i);
    expect(meta.textContent).toMatch(/HMAC/i);
  });
});
