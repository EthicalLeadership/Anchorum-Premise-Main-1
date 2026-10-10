// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { createAdapter } from "../adapter";
import { EvidenceViewer } from "./EvidenceViewer";
import { translate } from "../i18n";

afterEach(cleanup);
const view = (id: string) =>
  render(<EvidenceViewer locale="en" adapter={createAdapter({ backend: null })} caseId="CASE-2024-018" evidenceId={id} />);

describe("EvidenceViewer", () => {
  it("names the failing step for an integrity hold", async () => {
    view("E-1047");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(translate("en", "overview.integrity.step.hash"));
  });

  it("shows not yet verified when no verification exists", async () => {
    view("E-1045");
    expect(await screen.findByText(translate("en", "verification.not_yet_verified"))).toBeTruthy();
  });

  it("alerts on an unknown id", async () => {
    view("E-9999");
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});
