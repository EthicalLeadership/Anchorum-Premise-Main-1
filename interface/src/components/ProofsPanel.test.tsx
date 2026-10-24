// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ProofsReport, createAdapter } from "../adapter";
import { ProofsPanel } from "./ProofsPanel";

afterEach(cleanup);

type Adapter = ReturnType<typeof createAdapter>;

function adapterReturning(
  result: { ok: true; value: ProofsReport } | { ok: false; error: string },
): Adapter {
  return {
    audit: { verifyProofs: () => Promise.resolve(result) },
  } as unknown as Adapter;
}

const report: ProofsReport = {
  caseId: "C-1",
  status: "fail",
  verifiedAt: "2026-02-01T10:00:00Z",
  proofs: [
    {
      id: "audit_chain",
      status: "pass",
      code: "ok",
      failingItem: null,
      checked: 4,
    },
    {
      id: "evidence_content",
      status: "fail",
      code: "content_mismatch",
      failingItem: "E-1",
      checked: 1,
    },
    {
      id: "audit_hmac",
      status: "not_checked",
      code: "no_signing_key",
      failingItem: null,
      checked: 0,
    },
  ],
};

function renderPanel(adapter: Adapter, onVerified = () => {}) {
  return render(
    <ProofsPanel
      locale="en"
      adapter={adapter}
      caseId="C-1"
      timeZone="UTC"
      onVerified={onVerified}
    />,
  );
}

describe("ProofsPanel", () => {
  it("says nothing about proofs until it is asked", () => {
    renderPanel(adapterReturning({ ok: true, value: report }));
    expect(screen.queryByTestId("proofs-summary")).toBeNull();
  });

  it("renders every proof with the outcome the server reported", async () => {
    const onVerified = vi.fn();
    renderPanel(adapterReturning({ ok: true, value: report }), onVerified);
    fireEvent.click(screen.getByRole("button", { name: "Verify cryptographic proofs" }));

    await waitFor(() => expect(screen.getByTestId("proofs-summary")).toBeTruthy());
    expect(screen.getByTestId("proofs-summary").getAttribute("data-status")).toBe("fail");

    const items = document.querySelectorAll(".proofs-panel__item");
    expect(items.length).toBe(3);
    expect(document.querySelectorAll(".proofs-panel__item--pass").length).toBe(1);
    expect(document.querySelectorAll(".proofs-panel__item--fail").length).toBe(1);
    // A check that never ran is its own state, not a quieter pass.
    expect(document.querySelectorAll(".proofs-panel__item--not_checked").length).toBe(1);

    expect(screen.getByText(/the stored bytes do not match/i)).toBeTruthy();
    expect(screen.getByText(/E-1/)).toBeTruthy();
    expect(screen.getByText(/no signing key/i)).toBeTruthy();
    expect(onVerified).toHaveBeenCalled();
  });

  it("reports an unavailable verifier instead of inventing a verdict", async () => {
    renderPanel(adapterReturning({ ok: false, error: "FEATURE_UNAVAILABLE" }));
    fireEvent.click(screen.getByRole("button", { name: "Verify cryptographic proofs" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/needs the local API/i);
    expect(screen.queryByTestId("proofs-summary")).toBeNull();
  });
});
