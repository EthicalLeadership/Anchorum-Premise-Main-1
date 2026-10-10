// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createAdapter } from "../adapter";
import { Administration } from "./Administration";

afterEach(cleanup);

describe("Administration", () => {
  it("lists members and invites a member with a role and case assignment", async () => {
    render(
      <Administration locale="en" adapter={createAdapter({ backend: null })} />,
    );
    const table = await screen.findByRole("table", { name: "Members" });
    expect(within(table).getByRole("row", { name: /A\. Roy/ })).toBeInTheDocument();
    expect(within(table).getByText("a.roy@example.test")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "new.reviewer@example.test" },
    });
    fireEvent.change(screen.getByLabelText("Role"), {
      target: { value: "reviewer" },
    });
    fireEvent.click(screen.getByLabelText(/CASE-2024-018/));
    fireEvent.submit(screen.getByRole("form", { name: "Invite a member" }));

    const invitedEmail = await within(table).findByText("new.reviewer@example.test");
    expect(invitedEmail).toBeInTheDocument();
    expect(within(invitedEmail.closest("tr")!).getByText("Invited")).toBeInTheDocument();
    expect(within(table).getAllByText("CASE-2024-018")).toHaveLength(4);
    expect(screen.getByRole("status")).toHaveTextContent("Invitation added.");
  });

  it("shows a field-level validation message for an existing email", async () => {
    render(
      <Administration locale="en" adapter={createAdapter({ backend: null })} />,
    );
    await screen.findByRole("table", { name: "Members" });
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "a.roy@example.test" },
    });
    fireEvent.submit(screen.getByRole("form", { name: "Invite a member" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A member with this email is already listed.",
    );
  });

  it("requires a reason and audits a role change through the confirmation dialog", async () => {
    const adapter = createAdapter({ backend: null });
    render(<Administration locale="en" adapter={adapter} />);
    const table = await screen.findByRole("table", { name: "Members" });

    fireEvent.change(screen.getByRole("combobox", { name: "Change role for L. Chen" }), {
      target: { value: "auditor" },
    });
    const dialog = await screen.findByRole("dialog", { name: "Confirm change" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm change" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Enter a reason before confirming.",
    );

    fireEvent.change(within(dialog).getByLabelText("Reason"), {
      target: { value: "Temporary audit review" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm change" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Member role updated and audited.",
    );
    const chenRow = within(table).getByRole("row", { name: /L\. Chen/ });
    expect(within(chenRow).getByRole("combobox")).toHaveValue("auditor");

    const audit = await adapter.audit.list("CASE-2024-018");
    expect(audit.ok).toBe(true);
    if (audit.ok) {
      expect(audit.value.at(-1)).toMatchObject({
        event: "member_role_changed",
        memberId: "M-2",
        reason: "Temporary audit review",
      });
    }
  });
});
