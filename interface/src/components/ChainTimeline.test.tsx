// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { CustodyEntry } from "../adapter";
import { ChainTimeline } from "./ChainTimeline";

afterEach(cleanup);

const linked = (id: string, action = "uploaded"): CustodyEntry =>
  ({ id, action, actor: "system", at: "2024-09-01T10:00:00Z", chain: "linked" } as CustodyEntry);
const broken = (id: string, action = "verified"): CustodyEntry =>
  ({ id, action, actor: "system", at: "2024-09-01T10:05:00Z", chain: "broken" } as CustodyEntry);

describe("ChainTimeline", () => {
  it("renders one step per entry with a linked marker", () => {
    render(<ChainTimeline locale="en" entries={[linked("c1"), linked("c2")]} timeZone="UTC" />);
    const t = screen.getByTestId("chain-timeline");
    expect(t.getAttribute("data-state")).toBe("linked");
    expect(t.querySelectorAll(".chain-timeline__step").length).toBe(2);
    expect(t.querySelectorAll(".chain-timeline__step--broken").length).toBe(0);
  });

  it("marks a broken step and sets overall state to broken", () => {
    render(<ChainTimeline locale="en" entries={[linked("c1"), broken("c2")]} timeZone="UTC" />);
    const t = screen.getByTestId("chain-timeline");
    expect(t.getAttribute("data-state")).toBe("broken");
    expect(t.querySelectorAll(".chain-timeline__step--broken").length).toBe(1);
    expect(t.querySelectorAll(".chain-timeline__step--linked").length).toBe(1);
  });

  it("returns null for an empty list", () => {
    const { container } = render(<ChainTimeline locale="en" entries={[]} timeZone="UTC" />);
    expect(container.querySelector('[data-testid="chain-timeline"]')).toBeNull();
  });
});
