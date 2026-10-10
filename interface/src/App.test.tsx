// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
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
});
