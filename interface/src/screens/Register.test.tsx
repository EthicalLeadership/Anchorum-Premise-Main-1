// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";import { createAdapter, type Evidence } from "../adapter";
import { Register } from "./Register";

afterEach(cleanup);

describe("Register", () => {
  it("lists fixture evidence with links to the viewer", async () => {
    render(<Register locale="en" adapter={createAdapter({ backend: null })} caseId="CASE-2024-018" />);
    const link = await screen.findByText("E-1047");
    expect(link.closest("a")?.getAttribute("href")).toContain("/evidence/E-1047");
    expect(screen.getByText("E-1042")).toBeTruthy();
  });
});


describe("Register removal", () => {
  it("removes an evidence row after confirmation", async () => {
    const originalConfirm = window.confirm;
    window.confirm = () => true;
    try {
      render(
        <Register
          locale="en"
          adapter={createAdapter({ backend: null })}
          caseId="CASE-2024-018"
        />,
      );
      await screen.findByText("E-1042");
      const row = screen.getByText("E-1042").closest("tr");
      if (!row) throw new Error("row not found");
      const button = row.querySelector("button");
      if (!button) throw new Error("button not found");
      button.click();
      await screen.findByText("E-1047");
      expect(screen.queryByText("E-1042")).toBeNull();
    } finally {
      window.confirm = originalConfirm;
    }
  });
});
// An adapter whose register lists exactly the rows a test hands it, so a row
// can carry a status or badge the fixture never produces.
function adapterListing(
  rows: readonly Evidence[],
): ReturnType<typeof createAdapter> {
  const base = createAdapter({ backend: null });
  return {
    ...base,
    evidence: {
      ...base.evidence,
      list: () => Promise.resolve({ ok: true, value: rows }),
      // The stub lists rows the base adapter has never seen, so the base
      // would answer NOT_FOUND. Removal here only has to succeed.
      remove: (id: string) =>
        Promise.resolve({ ok: true, value: { id, removed: true } }),
    },
  };
}

function evidenceRow(overrides: Partial<Evidence> = {}): Evidence {
  return {
    id: "E-9001",
    name: "late-arrival.pdf",
    status: "extracted",
    badges: ["received", "stored"],
    quarantinedReason: null,
    holdReason: null,
    duplicateCandidate: false,
    category: null,
    source: null,
    ...overrides,
  };
}

describe("Register translation vocabulary", () => {
  // The live API reports statuses the offline fixture never uses (stored,
  // extracted, ...) and badges such as `stored`. Before the catalog carried
  // them, looking one up threw inside the status cell, React unmounted the
  // whole tree, and the operator was left with a blank page.
  it("renders a status and badges the fixture never uses", async () => {
    render(
      <Register
        locale="en"
        adapter={adapterListing([evidenceRow()])}
        caseId="CASE-2024-018"
      />,
    );
    expect(await screen.findByText("E-9001")).toBeTruthy();
    expect(screen.getByText("Extracted")).toBeTruthy();
    expect(screen.getByText("Received, Stored")).toBeTruthy();
  });

  it("translates the same vocabulary in French", async () => {
    render(
      <Register
        locale="fr"
        adapter={adapterListing([evidenceRow()])}
        caseId="CASE-2024-018"
      />,
    );
    expect(await screen.findByText("E-9001")).toBeTruthy();
    expect(screen.getByText("Extrait")).toBeTruthy();
    expect(screen.getByText("Reçu, Enregistré")).toBeTruthy();
  });

  it("renders an unknown status instead of crashing the screen", async () => {
    render(
      <Register
        locale="en"
        adapter={adapterListing([
          evidenceRow({ id: "E-9002", status: "not_a_real_status" }),
        ])}
        caseId="CASE-2024-018"
      />,
    );
    expect(await screen.findByText("E-9002")).toBeTruthy();
    // Unforeseen data is echoed rather than translated: visible, greppable,
    // and harmless, where throwing would be a blank page.
    expect(
      screen.getByText("evidence.status.not_a_real_status"),
    ).toBeTruthy();
  });

  it("renders an unknown badge instead of crashing the screen", async () => {
    render(
      <Register
        locale="en"
        adapter={adapterListing([
          evidenceRow({ id: "E-9003", badges: ["not_a_real_badge"] }),
        ])}
        caseId="CASE-2024-018"
      />,
    );
    expect(await screen.findByText("E-9003")).toBeTruthy();
    expect(screen.getByText("badge.not_a_real_badge")).toBeTruthy();
  });

  it("still renders a removable row for an unforeseen status", async () => {
    const originalConfirm = window.confirm;
    window.confirm = () => true;
    try {
      const list = [evidenceRow({ id: "E-9004", status: "not_a_real_status" })];
      render(
        <Register
          locale="en"
          adapter={adapterListing(list)}
          caseId="CASE-2024-018"
        />,
      );
      const link = await screen.findByText("E-9004");
      const row = link.closest("tr");
      if (!row) throw new Error("row not found");
      const button = row.querySelector("button");
      if (!button) throw new Error("button not found");
      expect(button.textContent).toBe("Remove");
      button.click();
      await waitFor(() => expect(screen.queryByText("E-9004")).toBeNull());
    } finally {
      window.confirm = originalConfirm;
    }
  });
});
describe("Register intake metadata", () => {
  it("renders the category and source columns", async () => {
    render(
      <Register
        locale="en"
        adapter={adapterListing([
          evidenceRow({ id: "E-9100", category: "medical", source: "clinic" }),
        ])}
        caseId="CASE-2024-018"
      />,
    );
    expect(await screen.findByText("E-9100")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Category" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Source" })).toBeTruthy();
    expect(screen.getByRole("table").querySelectorAll("tr")[1].textContent).toContain("Medical");
    expect(screen.getByRole("table").querySelectorAll("tr")[1].textContent).toContain("Clinic");
  });

  it("translates the metadata in French", async () => {
    render(
      <Register
        locale="fr"
        adapter={adapterListing([
          evidenceRow({ id: "E-9101", category: "payroll", source: "employer" }),
        ])}
        caseId="CASE-2024-018"
      />,
    );
    expect(await screen.findByText("E-9101")).toBeTruthy();
    expect(screen.getByRole("table").querySelectorAll("tr")[1].textContent).toContain("Paie");
    expect(screen.getByRole("table").querySelectorAll("tr")[1].textContent).toContain("Employeur");
  });

  it("shows a dash when the metadata was never set", async () => {
    render(
      <Register
        locale="en"
        adapter={adapterListing([evidenceRow({ id: "E-9102" })])}
        caseId="CASE-2024-018"
      />,
    );
    expect(await screen.findByText("E-9102")).toBeTruthy();
    // Two cells: category and source are both unset on this row.
    expect(screen.getAllByText("—")).toHaveLength(2);
  });

  it("renders an unrecognised category instead of crashing the screen", async () => {
    render(
      <Register
        locale="en"
        adapter={adapterListing([
          evidenceRow({ id: "E-9103", category: "not_a_real_category" }),
        ])}
        caseId="CASE-2024-018"
      />,
    );
    expect(await screen.findByText("E-9103")).toBeTruthy();
    expect(screen.getByText("evidence.category.not_a_real_category")).toBeTruthy();
  });
});
