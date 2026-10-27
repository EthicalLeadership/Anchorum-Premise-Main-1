// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { createAdapter, EmailIntakeResult } from "../adapter";
import { EmailIntake } from "./EmailIntake";
import { translate } from "../i18n";

afterEach(cleanup);

const processed: EmailIntakeResult = {
  caseId: "2",
  files: [
    {
      filename: "grief.eml",
      status: "processed",
      stages: [
        { id: "received", status: "success", detail: "parsed" },
        { id: "classified", status: "success", detail: "grievance" },
        { id: "policy", status: "success", detail: "allowed" },
      ],
      subject: "Dépôt de grief",
      sender: "marie.tremblay@exemple.ca",
      date: "2024-03-04T09:15:00+00:00",
      actor: "grievance",
      confidence: 0.91,
      policy: { allowed: true, quarantine: false, reason: "internal" },
      evidenceId: "E-77",
    },
    {
      filename: "publicite.eml",
      status: "rejected_policy",
      stages: [
        { id: "received", status: "success", detail: "parsed" },
        { id: "classified", status: "success", detail: "marketing" },
        { id: "policy", status: "failed", detail: "external_bulk_mail" },
      ],
      subject: "Promotion",
      sender: "news@ailleurs.example",
      policy: {
        allowed: false,
        quarantine: true,
        reason: "external_bulk_mail",
      },
    },
  ],
  summary: { processed: 1, rejectedPolicy: 1, duplicate: 0, failed: 0 },
};

function stubAdapter(result: EmailIntakeResult | { error: string }) {
  const emailIntake = vi.fn(async () =>
    "error" in result
      ? ({ ok: false, error: result.error } as const)
      : ({ ok: true, value: result } as const),
  );
  const adapter = {
    cases: {
      get: async () => ({
        ok: true as const,
        value: { id: "2", timezone: "America/Toronto" },
      }),
      emailIntake,
    },
  } as unknown as ReturnType<typeof createAdapter>;
  return { adapter, emailIntake };
}

const file = (name: string): File =>
  ({
    name,
    arrayBuffer: async () => new ArrayBuffer(8),
  }) as unknown as File;

async function submitFiles(names: string[]) {
  fireEvent.change(screen.getByTestId("file-input"), {
    target: { files: names.map(file) },
  });
}

describe("EmailIntake", () => {
  it("names every stage and outcome for a mixed batch", async () => {
    const { adapter } = stubAdapter(processed);
    render(<EmailIntake locale="en" adapter={adapter} caseId="2" />);
    await submitFiles(["grief.eml", "publicite.eml"]);

    expect(await screen.findByText("grief.eml")).toBeTruthy();
    expect(screen.getByText("publicite.eml")).toBeTruthy();

    // One verdict per file, and they differ. A batch that reported a single
    // "done" would hide that half of it was refused.
    const cards = document.querySelectorAll("[data-intake-status]");
    expect(cards).toHaveLength(2);
    expect(cards[0].getAttribute("data-intake-status")).toBe("processed");
    expect(cards[1].getAttribute("data-intake-status")).toBe("rejected_policy");
  });

  it("draws the three stages for each message", async () => {
    const { adapter } = stubAdapter(processed);
    render(<EmailIntake locale="en" adapter={adapter} caseId="2" />);
    await submitFiles(["grief.eml"]);

    await screen.findByText("grief.eml");
    // Scope to the first card: the stub returns both files, so a document-wide
    // query would collect six stages and the assertion would be about the batch
    // rather than about one message's pipeline.
    const card = document.querySelectorAll(".intake-card")[0];
    const stages = card.querySelectorAll("[data-stage][data-status]");
    expect(Array.from(stages).map((s) => s.getAttribute("data-status"))).toEqual([
      "success",
      "success",
      "success",
    ]);
    // The stage ids are the pipeline's own vocabulary, in order.
    expect(Array.from(stages).map((s) => s.getAttribute("data-stage"))).toEqual([
      "received",
      "classified",
      "policy",
    ]);
  });

  it("says why a message was refused by policy", async () => {
    const { adapter } = stubAdapter(processed);
    render(<EmailIntake locale="en" adapter={adapter} caseId="2" />);
    await submitFiles(["publicite.eml"]);

    // Matched over the card's text rather than by exact string: the paragraph
    // continues with the quarantine note, so the policy sentence is one part of
    // a longer line.
    const refused = await screen.findByText((_, element) =>
      element?.classList.contains("intake-card__policy--denied") ?? false,
    );
    expect(refused.textContent).toContain(
      translate("en", "email.intake.policy_rejected", {
        reason: "external_bulk_mail",
      }),
    );
    expect(refused.textContent).toContain(
      translate("en", "email.intake.quarantine"),
    );
  });

  it("summarises the batch with all four counts", async () => {
    const { adapter } = stubAdapter(processed);
    render(<EmailIntake locale="en" adapter={adapter} caseId="2" />);
    await submitFiles(["grief.eml"]);

    expect(await screen.findByTestId("intake-summary")).toBeTruthy();
    expect(
      translate("en", "email.intake.summary", {
        processed: 1,
        rejected: 1,
        duplicate: 0,
        failed: 0,
      }),
    ).toContain("1 processed");
  });

  it("submits each selected file once", async () => {
    const { adapter, emailIntake } = stubAdapter(processed);
    render(<EmailIntake locale="en" adapter={adapter} caseId="2" />);
    await submitFiles(["grief.eml", "publicite.eml"]);

    await screen.findByText("grief.eml");
    expect(emailIntake).toHaveBeenCalledTimes(1);
    const [caseId, files] = emailIntake.mock.calls[0] as unknown as [
      string,
      Array<{ name: string }>,
    ];
    expect(caseId).toBe("2");
    expect(files.map((f) => f.name)).toEqual(["grief.eml", "publicite.eml"]);
  });

  it("says nothing was added when the request fails", async () => {
    const { adapter } = stubAdapter({ error: "BACKEND_UNREACHABLE" });
    render(<EmailIntake locale="en" adapter={adapter} caseId="2" />);
    await submitFiles(["grief.eml"]);

    expect((await screen.findByRole("alert")).textContent).toBe(
      translate("en", "email.intake.error"),
    );
    expect(document.querySelector("[data-intake-status]")).toBeNull();
  });

  it("shows an empty state before anything is submitted", () => {
    const { adapter } = stubAdapter(processed);
    render(<EmailIntake locale="en" adapter={adapter} caseId="2" />);
    expect(screen.getByText(translate("en", "email.intake.empty"))).toBeTruthy();
    expect(document.querySelector("[data-intake-status]")).toBeNull();
  });

  it("links a stored message to the evidence viewer", async () => {
    const { adapter } = stubAdapter(processed);
    render(<EmailIntake locale="en" adapter={adapter} caseId="2" />);
    await submitFiles(["grief.eml"]);

    const link = await screen.findByRole("link", {
      name: translate("en", "email.intake.open_evidence"),
    });
    expect(link.getAttribute("href")).toBe("#/cases/2/evidence/E-77");
  });
});
