// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createAdapter, type AnchorState } from "../adapter";
import { AnchorPanel } from "./AnchorPanel";

afterEach(cleanup);

const DIGEST = "a".repeat(64);
const OTHER = "b".repeat(64);

type PublishResult =
  | { ok: true; value: AnchorState }
  | { ok: false; error: string };

function adapterWith(anchor: AnchorState, publish?: () => Promise<PublishResult>) {
  const base = createAdapter({ backend: null });
  return {
    ...base,
    anchoring: {
      get: () => Promise.resolve({ ok: true as const, value: anchor }),
      publish:
        publish ?? (() => Promise.resolve({ ok: true as const, value: anchor })),
    },
  };
}

describe("AnchorPanel", () => {
  it("says the deployment is unconfigured and refuses to publish", async () => {
    const adapter = adapterWith({
      anchored: false,
      configured: false,
      expectedName: "case-1.example.test",
    });
    render(<AnchorPanel locale="en" adapter={adapter} caseId="1" />);

    expect(await screen.findByText(/No DNS zone is configured/i)).toBeTruthy();
    expect(screen.getByText(/case-1\.example\.test/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Publish anchor/i })).toBeDisabled();
  });

  it("shows the published record without a staleness warning", async () => {
    const adapter = adapterWith({
      anchored: true,
      configured: true,
      digest: DIGEST,
      currentDigest: DIGEST,
      recordName: "case-1.example.test",
      publishedAt: "2026-02-01T10:00:00Z",
      stale: false,
    });
    const { container } = render(<AnchorPanel locale="en" adapter={adapter} caseId="1" />);

    expect(await screen.findByText("case-1.example.test")).toBeTruthy();
    // The whole digest stays available on the element even though the visible
    // text is abbreviated, so a reader can copy the value they must compare.
    const digestCell = container.querySelector(".anchor-panel__mono[title]");
    expect(digestCell?.getAttribute("title")).toBe(DIGEST);
    expect(screen.queryByText(/has changed since this anchor/i)).toBeNull();
  });

  it("warns when the evidence moved after publication", async () => {
    const adapter = adapterWith({
      anchored: true,
      configured: true,
      digest: DIGEST,
      currentDigest: OTHER,
      recordName: "case-1.example.test",
      stale: true,
    });
    render(<AnchorPanel locale="en" adapter={adapter} caseId="1" />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/has changed since this anchor/i);
  });

  it("reports a rejected publication instead of showing it as anchored", async () => {
    const adapter = adapterWith(
      { anchored: false, configured: true, expectedName: "case-1.example.test" },
      () => Promise.resolve({ ok: false as const, error: "ANCHOR_PUBLISH_FAILED" }),
    );
    render(<AnchorPanel locale="en" adapter={adapter} caseId="1" />);

    const button = await screen.findByRole("button", { name: /Publish anchor/i });
    fireEvent.click(button);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/rejected the record/i);
    expect(screen.queryByText(/Published digest/i)).toBeNull();
  });
});
