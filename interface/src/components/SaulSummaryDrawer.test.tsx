// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SaulSummaryDrawer } from "./SaulSummaryDrawer";
import type { SummaryResult } from "../adapter";
import { translate } from "../i18n";

afterEach(cleanup);

const summary: SummaryResult = {
  id: "E-1",
  narrative: {
    narrative:
      "## Faits établis\n\n- Les prestations courent jusqu'au **27 avril 2026**.\n",
    model: "qwen2.5:7b",
    prompt: "analyze_claim.txt@v1",
  },
  claims: [
    {
      text: "Les prestations courent jusqu'au 27 avril 2026",
      quote: "Benefits are approved until April 27, 2026",
      basis: "explicit",
      confidence: "direct",
      source: {
        quote: "Benefits are approved until April 27, 2026",
        span_normalized: [10, 52],
      },
    },
    {
      text: "La lettre ne précise pas la date de réévaluation",
      quote: null,
      basis: "absence",
      confidence: "inferred",
      source: { quote: null, span_normalized: null },
    },
  ],
  validation: {
    verified: 1,
    inferred: 1,
    rejected: 1,
    total: 3,
    rejected_claims: [
      {
        claim_text: "L'assureur impose une pénalité de 500 $ par jour",
        attempted_quote: "the insurer will impose a $500 daily penalty",
        reason: "quote not verbatim in the document",
      },
    ],
  },
  generatedAt: "2026-04-27T14:30:00+00:00",
};

function renderDrawer(overrides: Partial<Parameters<typeof SaulSummaryDrawer>[0]> = {}) {
  return render(
    <SaulSummaryDrawer
      locale="en"
      open
      loading={false}
      summary={summary}
      timeZone="America/Toronto"
      onClose={() => {}}
      {...overrides}
    />,
  );
}

describe("SaulSummaryDrawer", () => {
  it("renders the narrative as markup rather than as source text", () => {
    renderDrawer();
    // A heading and a list item: if the markdown were shown literally the text
    // would contain "##" and "-", and there would be no <strong> at all.
    expect(screen.getByRole("heading", { name: "Faits établis" })).toBeTruthy();
    expect(screen.getByText("27 avril 2026").tagName).toBe("STRONG");
  });

  it("shows each claim with the quote it was checked against", () => {
    renderDrawer();
    const verified = document.querySelector('.claim[data-claim="direct"]');
    expect(verified?.textContent).toContain("Benefits are approved until April 27, 2026");
    const inferred = document.querySelector('.claim[data-claim="inferred"]');
    expect(inferred?.textContent).toContain(
      translate("en", "evidence.viewer.summary.inferred_note"),
    );
  });

  it("lists rejected claims with their quote and the reason", () => {
    renderDrawer();
    const rejected = document.querySelector('.claim[data-claim="rejected"]');
    expect(rejected?.textContent).toContain("$500 daily penalty");
    expect(rejected?.textContent).toContain("quote not verbatim in the document");
  });

  it("counts verified, inferred and rejected separately", () => {
    renderDrawer();
    const counts = (name: string) =>
      document.querySelector(`[data-claim-count="${name}"]`)?.textContent ?? "";
    expect(counts("verified")).toBe(
      translate("en", "evidence.viewer.summary.verified_count", { count: 1 }),
    );
    expect(counts("inferred")).toBe(
      translate("en", "evidence.viewer.summary.inferred_count", { count: 1 }),
    );
    expect(counts("rejected")).toBe(
      translate("en", "evidence.viewer.summary.rejected_count", { count: 1 }),
    );
  });

  it("says no summary exists instead of showing an empty document", () => {
    renderDrawer({
      summary: { id: "E-1", narrative: null, claims: [], validation: null, reason: "NOT_GENERATED" },
    });
    expect(
      screen.getByText(translate("en", "evidence.viewer.summary.not_generated")),
    ).toBeTruthy();
  });

  it("says the summariser is off when the model is disabled", () => {
    renderDrawer({
      summary: { id: "E-1", narrative: null, claims: [], validation: null, reason: "LLM_DISABLED" },
    });
    expect(
      screen.getByText(translate("en", "evidence.viewer.summary.disabled")),
    ).toBeTruthy();
  });

  it("reports a model error rather than an empty narrative", () => {
    renderDrawer({
      summary: {
        id: "E-1",
        narrative: { narrative: "", error: "OLLAMA_UNREACHABLE: URLError" },
        claims: [],
        validation: {
          verified: 0,
          inferred: 0,
          rejected: 0,
          total: 0,
          rejected_claims: [],
          notRun: "OLLAMA_UNREACHABLE: URLError",
        },
      },
    });
    // Two alerts on purpose: one for the model error and one for "claims were
    // not checked". They answer different questions and neither implies the
    // other, so both must be present.
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(2);
    expect(alerts[0].textContent).toContain("OLLAMA_UNREACHABLE: URLError");
    // The zeroed counters must be explained, not left as a clean-looking score.
    expect(
      screen.getByText(
        translate("en", "evidence.viewer.summary.not_run", {
          reason: "OLLAMA_UNREACHABLE: URLError",
        }),
      ),
    ).toBeTruthy();
  });

  it("shows a loading status while the summary is being written", () => {
    renderDrawer({ loading: true, summary: null });
    expect(
      screen.getByText(translate("en", "evidence.viewer.summary.loading")),
    ).toBeTruthy();
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    renderDrawer({ onClose });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("renders nothing when closed", () => {
    const { container } = renderDrawer({ open: false });
    expect(container.querySelector(".saul-drawer")).toBeNull();
  });
});
