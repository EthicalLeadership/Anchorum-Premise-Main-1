// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createAdapter } from "../adapter";
import { CaseList } from "./CaseList";

const adapter = createAdapter({ backend: null });

describe("CaseList", () => {
  it("renders the fixture case as one row with hold count and create link", async () => {
    render(<CaseList locale="en" adapter={adapter} />);
    await waitFor(() => screen.getByText("DUPONT v. ACME"));
    expect(screen.getAllByRole("row")).toHaveLength(2);
    const cells = screen.getAllByRole("cell").map((c) => c.textContent);
    expect(cells[5]).toBe("1");
    expect(screen.getByRole("link", { name: /create/i }).getAttribute("href")).toBe("#/cases/new");
  });

  it("renders the empty state with Create case", async () => {
    const empty = { ...adapter, cases: { ...adapter.cases, list: async () => ({ ok: true as const, value: [] }) } };
    render(<CaseList locale="en" adapter={empty} />);
    await waitFor(() => screen.getByRole("link", { name: /create/i }));
  });

  it("renders permission_limited", () => {
    render(<CaseList locale="en" adapter={adapter} permissionLimited />);
    expect(screen.getByRole("status")).toBeTruthy();
  });

  it("cannot reach no-matches with the fixture-derived status options", async () => {
    render(<CaseList locale="en" adapter={adapter} />);
    await waitFor(() => screen.getByText("DUPONT v. ACME"));
    const status = screen.getAllByRole("combobox")[0] as HTMLSelectElement;
    expect(Array.from(status.options, (option) => option.value)).toEqual(["", "open"]);
    expect(screen.queryByText("No cases match these filters.")).toBeNull();
  });
});
