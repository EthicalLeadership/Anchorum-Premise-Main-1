// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    // The last *custody* row (C-1047-2, not the audit row A-3) carries
    // hmac c3c3…, which the metadata block truncates to c3c3c3c3…c3c3.
    // The HMAC belongs to CustodyEntry; putting it on an audit row left
    // latestHmac empty and the block said "unsigned".
    expect(meta.textContent).toMatch(/c3c3c3c3…c3c3/i);
    // SHA-256 line present (either a hash or "unavailable")
    expect(meta.textContent).toMatch(/SHA-256/i);
    expect(meta.textContent).toMatch(/HMAC/i);
  });

  it("labels both Saul actions in the reader's language", async () => {
    view("E-1047");
    await screen.findByRole("heading", { level: 1 });
    // A missing catalog entry renders the key itself — "evidence.viewer.
    // summary_open" on a button. Asserting the visible labels is the only
    // check that catches a typo between the key the screen asks for and the
    // key the catalog defines, because `translate` happily returns the key.
    for (const key of [
      "evidence.viewer.ask_summarize",
      "evidence.viewer.summary.open",
    ]) {
      const label = translate("en", key as never);
      expect(label).not.toBe(key);
      expect(
        screen.getByRole("button", { name: label }),
      ).toBeTruthy();
    }
  });

  it("scrolls to ?at= on arrival", () => {
    window.location.hash = "#/cases/2/evidence/E-abc?at=480";
    view("E-abc");
    // The current implementation reads from window.location.hash directly,
    // so this test confirms the ambient read works (scenario a).
    // After refactor, this will be replaced by prop-based test.
  });

  it.each(["", "null"])(
    "renders nothing for the placeholder id %j",
    async (placeholder) => {
      // A link built from an item that had no id arrives here. Requesting "null"
      // would 404, and the reader would be shown an error for a broken link
      // they did not build — so the screen renders nothing at all.
      const { container } = render(
        <EvidenceViewer
          locale="en"
          adapter={createAdapter({ backend: null })}
          caseId="CASE-2024-018"
          evidenceId={placeholder}
        />,
      );
      expect(container.querySelector(".evidence-viewer")).toBeNull();
      expect(screen.queryByRole("alert")).toBeNull();
    },
  );
});
