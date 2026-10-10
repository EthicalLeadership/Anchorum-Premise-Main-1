// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createAdapter } from "../adapter";
import { Timeline } from "./Timeline";

afterEach(cleanup);

describe("Timeline", () => {
  it("shows all date precisions and source links", async () => {
    render(
      <Timeline
        locale="en"
        adapter={createAdapter({ backend: null })}
        caseId="CASE-2024-018"
      />,
    );
    expect(await screen.findByText("Grievance filed")).toBeTruthy();
    const timelineText = screen.getByRole("list").textContent ?? "";
    expect(timelineText).toContain("Date precision: exact");
    expect(timelineText).toContain("Date precision: range");
    expect(timelineText).toContain("Date precision: approximate");
    expect(timelineText).toContain("Date precision: unknown");
    expect(screen.getByText("Unknown date")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Source: E-1043" }).getAttribute("href"))
      .toContain("/evidence/E-1043");
  });

  it("filters timeline rows by person", async () => {
    render(
      <Timeline
        locale="en"
        adapter={createAdapter({ backend: null })}
        caseId="CASE-2024-018"
      />,
    );
    await screen.findByText("Grievance filed");
    fireEvent.change(screen.getByLabelText("Person"), {
      target: { value: "witness" },
    });
    const list = screen.getByRole("list");
    expect(within(list).getByText("Witness statement")).toBeTruthy();
    expect(within(list).queryByText("Grievance filed")).toBeNull();
  });

  it("renders an error state for an unknown case", async () => {
    render(
      <Timeline
        locale="en"
        adapter={createAdapter({ backend: null })}
        caseId="missing"
      />,
    );
    expect(await screen.findByText("Not found")).toBeTruthy();
  });
});
