// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createAdapter } from "../adapter";
import { Search } from "./Search";

afterEach(cleanup);
const go = (a: ReturnType<typeof createAdapter>, caseId: string, q: string) => {
  render(<Search locale="en" adapter={a} caseId={caseId} />);
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: q } });
  fireEvent.submit(screen.getByRole("search"));
};

describe("Search", () => {
  it("shows matches linking to the viewer", async () => {
    go(createAdapter({ backend: null }), "CASE-2024-018", "witness");
    expect(await screen.findByText(/Witness statement/)).toBeTruthy();
    expect(screen.getAllByRole("link")[0].getAttribute("href")).toContain("/evidence/E-1046");
  });
  it("shows no-results", async () => {
    go(createAdapter({ backend: null }), "CASE-2024-018", "zzzz");
    expect(await screen.findByText("No matches. Try a broader term.")).toBeTruthy();
  });
  it("shows index building", async () => {
    go(createAdapter({ backend: null, searchIndexReady: false }), "CASE-2024-018", "a");
    expect(await screen.findByRole("status")).toBeTruthy();
  });
  it("shows the search-specific unavailable message when the backend cannot be reached", async () => {
    go(
      createAdapter({ backend: { baseUrl: "http://invalid.invalid" } }),
      "CASE-2024-018",
      "witness",
    );
    expect(await screen.findByText("Search is unavailable.")).toBeTruthy();
  });
  it("shows not found for foreign case", async () => {
    go(createAdapter({ backend: null }), "X", "a");
    expect(await screen.findByText("Not found")).toBeTruthy();
  });
});
