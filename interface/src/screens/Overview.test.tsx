// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { createAdapter } from "../adapter";
import { Overview } from "./Overview";
import { translate } from "../i18n";

afterEach(cleanup);

describe("Overview", () => {
  it("names the failing step and shows four steps without numerals", async () => {
    render(<Overview locale="en" adapter={createAdapter({ backend: null })} caseId="CASE-2024-018" />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(translate("en", "overview.integrity.step.hash"));
    expect(document.querySelectorAll(".verification-steps li")).toHaveLength(4);
    expect(document.querySelectorAll(".verification-segments .segment")).toHaveLength(4);
    expect(document.querySelector(".verification-segments")?.textContent).toBe("");
  });

  it("renders an error for an unknown case", async () => {
    render(<Overview locale="en" adapter={createAdapter({ backend: null })} caseId="nope" />);
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});
