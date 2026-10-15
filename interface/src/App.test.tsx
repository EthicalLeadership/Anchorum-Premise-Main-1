// @vitest-environment jsdom
import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("App session seam", () => {
  it("loads the fixture session and passes it to the shell", async () => {
    render(<App />);

    expect(
      await screen.findByRole("button", { name: /A\. Roy/i }),
    ).toBeInTheDocument();
  });

  it("renders the case header on a case-scoped route", async () => {
    window.location.hash = "#/cases/CASE-2024-018/audit";
    render(<App />);
    await waitFor(() =>
      expect(document.querySelector(".case-header")).toBeTruthy(),
    );
  });

  it("renders the overview on its case navigation route", async () => {
    window.location.hash = "#/cases/CASE-2024-018/overview";
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Verification" }),
    ).toBeInTheDocument();
    expect(document.querySelector(".case-header")).toBeTruthy();
    expect(document.querySelector(".rail")).toBeTruthy();
  });

  it("keeps case navigation inside the hash-routed UI", async () => {
    window.location.hash = "#/cases/CASE-2024-018/evidence";
    render(<App />);

    await waitFor(() =>
      expect(document.querySelector(".case-header")).toBeTruthy(),
    );
    const evidenceLink = await within(
      screen.getByRole("navigation", { name: "Case navigation" }),
    ).findByRole("link", { name: "Evidence" });
    expect(evidenceLink).toHaveAttribute(
      "href",
      "#/cases/CASE-2024-018/evidence",
    );
    expect(
      within(
        screen.getByRole("navigation", { name: "Primary navigation" }),
      ).getByRole("link", { name: "Cases" }),
    ).toHaveAttribute("href", "#/cases");
  });

  it("offers a cases-list return link when a case is missing", async () => {
    window.location.hash = "#/cases/missing-case/evidence";
    render(<App />);

    expect(await screen.findByText("Not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Browse cases" })).toHaveAttribute(
      "href",
      "#/cases",
    );
  });
});
