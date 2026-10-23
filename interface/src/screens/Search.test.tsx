
// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
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

  // ---- acd1f42: hit lands in the viewer at the matched offset ----
  const withHits = (
    hits: { id: string; excerpt: string; offset?: number; line?: number }[],
  ) => {
    const a = createAdapter({ backend: null });
    vi.spyOn(a.search, "query").mockResolvedValue({ ok: true, value: hits } as never);
    return a;
  };

  it("carries ?at and q in the link when the hit has an offset", async () => {
    // Fixture row E-1046 ships offset: 1288
    go(createAdapter({ backend: null }), "CASE-2024-018", "witness");
    const href = (await screen.findByText(/Witness statement/))
      .closest("li")!
      .querySelector("a")!
      .getAttribute("href")!;
    expect(href).toContain("?at=1288");
    expect(href).toContain("q=witness");
  });

  it("omits the query string when the hit has no offset", async () => {
    go(
      withHits([{ id: "E-1046", excerpt: "witness statement" }]),
      "CASE-2024-018",
      "witness",
    );
    const href = (await screen.findByText(/witness statement/))
      .closest("li")!
      .querySelector("a")!
      .getAttribute("href")!;
    expect(href).not.toContain("?");
  });

  it("renders the line when the hit carries one", async () => {
    go(
      withHits([{ id: "E-1046", excerpt: "witness statement", offset: 100, line: 12 }]),
      "CASE-2024-018",
      "witness",
    );
    expect(await screen.findByText(/line 12/)).toBeTruthy();
  });

  it("falls back to the offset when the hit has no line", async () => {
    go(
      withHits([{ id: "E-1046", excerpt: "witness statement", offset: 100 }]),
      "CASE-2024-018",
      "witness",
    );
    expect(await screen.findByText(/offset 100/)).toBeTruthy();
  });

  it("gives two hits in one document distinct keys and distinct ?at", async () => {
    go(
      withHits([
        { id: "E-1046", excerpt: "first witness", offset: 100 },
        { id: "E-1046", excerpt: "second witness", offset: 900 },
      ]),
      "CASE-2024-018",
      "witness",
    );
    await screen.findByText(/first witness/);
    const hrefs = screen
      .getAllByRole("link")
      .map((a) => a.getAttribute("href")!)
      .filter((h) => h.includes("/evidence/E-1046"));
    // Each hit renders two anchors (id link + "open exact") with the same
    // target, so unique targets should be exactly two, one per offset.
    const unique = [...new Set(hrefs)];
    expect(unique).toHaveLength(2);
    expect(unique.some((h) => h.includes("at=100"))).toBe(true);
    expect(unique.some((h) => h.includes("at=900"))).toBe(true);
  });
});
