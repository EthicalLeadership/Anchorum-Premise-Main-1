// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { createAdapter } from "../adapter";
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
