// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { createAdapter } from "../adapter";
import { AuditExports } from "./AuditExports";

afterEach(cleanup);

describe("AuditExports", () => {
  it("shows audit-chain outcomes and disables exports blocked by a named gate", async () => {
    const { container } = render(
      <AuditExports
        locale="en"
        adapter={createAdapter({ backend: null })}
        caseId="CASE-2024-018"
      />,
    );

    expect(await screen.findByRole("table", { name: "Audit log" })).toBeTruthy();
    expect(screen.getByText("broken Hash mismatch at readback")).toBeTruthy();
    expect(container.querySelector(".audit-chain--broken")).toHaveTextContent(
      "broken Hash mismatch at readback",
    );
    expect(container.querySelector(".audit-chain--linked")).toHaveTextContent("linked");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Export blocked: Barreau check E-1047",
    );
    expect(screen.getByRole("button", { name: "Export" })).toBeDisabled();
  });

  it("shows a broken-chain badge naming the first broken row", async () => {
    render(
      <AuditExports
        locale="en"
        adapter={createAdapter({ backend: null })}
        caseId="CASE-2024-018"
      />,
    );
    const badge = await screen.findByTestId("chain-summary");
    expect(badge).toHaveTextContent(/Chain broken at ID \S+/i);
    expect(badge.className).toContain("audit-chain-summary--broken");
  });

  it("shows not found for an unknown case", async () => {
    render(
      <AuditExports
        locale="en"
        adapter={createAdapter({ backend: null })}
        caseId="missing"
      />,
    );

    expect(await screen.findByText("Not found")).toBeTruthy();
  });

  it("treats chainIntegrity=broken as broken even when chain is not broken", async () => {
    const adapter = createAdapter({ backend: null });
    vi.spyOn(adapter.audit, "list").mockResolvedValue({
      ok: true,
      value: [
        { id: "A-1", event: "evidence_uploaded", evidenceId: "E-1047", chain: "linked" },
        { id: "A-9", event: "chain_break", evidenceId: "E-1047", chain: "linked", chainIntegrity: "broken" },
      ],
    } as never);
    render(<AuditExports locale="en" adapter={adapter} caseId="CASE-2024-018" />);
    const badge = await screen.findByTestId("chain-summary");
    expect(badge).toHaveTextContent(/Chain broken at ID A-9/i);
    expect(badge.className).toContain("audit-chain-summary--broken");
  });

  it("renders include-summary checkbox default-checked", async () => {
    render(
      <AuditExports
        locale="en"
        adapter={createAdapter({ backend: null })}
        caseId="CASE-2024-018"
      />,
    );
    const checkbox = await screen.findByRole("checkbox", { name: /SUMMARY\.md/i });
    expect(checkbox).toBeChecked();
  });
});
