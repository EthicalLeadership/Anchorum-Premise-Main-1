import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";
import type { DrawerObject, ShellBootstrap } from "../types";

const testCase: NonNullable<ShellBootstrap["case"]> = {
  id: "case/42",
  key: "MAT-42",
  title: "Matter 42",
  jurisdiction: "FR",
  timezone: "America/Toronto",
  status: "open",
  holdCount: 1,
  integrityStatus: "hold",
};

const bootstrap: ShellBootstrap = {
  locale: "en",
  session: { name: "Operator", role: "reviewer" },
  case: testCase,
  activeSection: "evidence",
  activeGlobalSection: "evidence",
  permissions: {
    canSeeSection: (section) => section === "evidence",
    canSeeGlobalSection: (section) => section === "evidence",
  },
  routes: {
    cases: "/cases",
    signIn: "/auth/login",
    signOut: "/auth/signout",
    administration: "#/admin",
    globalSection: (section) => `/${section}`,
    caseSection: (caseId, section) =>
      `/cases/${encodeURIComponent(caseId)}/${section}`,
    evidenceHolds: (caseId) =>
      `/cases/${encodeURIComponent(caseId)}/evidence?filter=hold`,
  },
};

const item: DrawerObject = {
  id: "ev-42",
  custody: [
    {
      id: "event-1",
      actor: "Operator",
      action: "uploaded",
      at: "2026-01-01T10:00:00Z",
      chain: "linked",
    },
  ],
  parent: null,
  source: "upload",
  parserVersion: "1.0",
  verification: { outcome: "fail", failingStep: "original-readback" },
  corrections: [],
};

function renderShell(onVerify?: (value: DrawerObject) => Promise<void>) {
  return render(
    <AppShell {...bootstrap} onVerify={onVerify}>
      {({ openDrawer }) => (
        <button
          type="button"
          onClick={(event) => openDrawer(item, event.currentTarget)}
        >
          Open evidence details
        </button>
      )}
    </AppShell>,
  );
}

describe("AppShell", () => {
  it("filters navigation and marks held integrity without relying on color", () => {
    renderShell();

    expect(
      within(screen.getByRole("navigation", { name: "Case navigation" })).getByRole(
        "link",
        { name: "Evidence" },
      ),
    ).toHaveAttribute(
      "href",
      "/cases/case%2F42/evidence",
    );
    expect(
      within(
        screen.getByRole("navigation", { name: "Primary navigation" }),
      ).getByRole("link", { name: "Evidence" }),
    ).toHaveAttribute("href", "/evidence");
    expect(
      within(
        screen.getByRole("navigation", { name: "Case navigation" }),
      ).queryByRole("link", { name: "Settings" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "1 item on hold",
      }),
    ).toHaveAttribute("href", "/cases/case%2F42/evidence?filter=hold");
  });

  it("does not describe an unknown integrity state as clear", () => {
    render(
      <AppShell
        {...bootstrap}
        case={{ ...testCase, holdCount: 0, integrityStatus: "unknown" }}
      >
        <p>Workspace</p>
      </AppShell>,
    );

    expect(screen.getByText("Integrity status unknown")).toBeInTheDocument();
    expect(screen.queryByText("All clear")).not.toBeInTheDocument();
  });

  it("localizes case, custody, and timestamps in the case timezone", () => {
    render(
      <AppShell {...bootstrap} locale="fr">
        {({ openDrawer }) => (
          <button
            type="button"
            onClick={(event) => openDrawer(item, event.currentTarget)}
          >
            Ouvrir les détails
          </button>
        )}
      </AppShell>,
    );

    expect(
      screen.getByRole("link", {
        name: "1 élément en suspens",
      }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ouvrir les détails" }));

    expect(screen.getByText("téléversé")).toBeInTheDocument();
    expect(screen.getByText("liée")).toBeInTheDocument();
    const custodyTime = screen.getByText(
      new Intl.DateTimeFormat("fr", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: testCase.timezone,
      }).format(new Date(item.custody[0].at)),
    );
    expect(custodyTime).toHaveAttribute("dateTime", item.custody[0].at);
  });

  it("opens the detail drawer, focuses it, and returns focus on Escape", async () => {
    renderShell();
    const trigger = screen.getByRole("button", {
      name: "Open evidence details",
    });

    fireEvent.click(trigger);

    expect(screen.getByRole("complementary", { name: "Evidence details" })).toBeVisible();
    expect(screen.getByText("Fail")).toBeInTheDocument();
    expect(screen.getByText("Failing step: original-readback")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close details" })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(document.querySelector("#right-drawer")).toHaveAttribute("hidden");
  });

  it("closes the user menu and returns focus to its trigger on Escape", async () => {
    renderShell();
    const trigger = screen.getByRole("button", { name: /Operator/ });

    fireEvent.click(trigger);
    const menu = document.getElementById("user-menu")!;
    expect(menu).not.toHaveAttribute("hidden");

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(menu).toHaveAttribute("hidden");
  });

  it("shows tenant administration only to tenant administrators", () => {
    const { rerender } = renderShell();
    fireEvent.click(screen.getByRole("button", { name: /Operator/ }));
    expect(
      screen.queryByRole("link", { name: "Administration" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Operator/ }));

    rerender(
      <AppShell
        {...bootstrap}
        session={{ name: "Admin", role: "case_admin" }}
        permissions={{
          ...bootstrap.permissions,
          canSeeGlobalSection: (section) => section === "admin",
        }}
        activeGlobalSection="admin"
      >
        <p>Workspace</p>
      </AppShell>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Admin/ }));
    expect(screen.getByRole("link", { name: "Administration" })).toHaveAttribute(
      "href",
      "#/admin",
    );
  });

  describe("role-gated rail", () => {
    const open = (role: "case_admin" | "reviewer" | "auditor") =>
      render(
        <AppShell
          {...bootstrap}
          session={{ name: "Tester", role }}
          permissions={{
            ...bootstrap.permissions,
            canSeeSection: (section) =>
              role === "case_admin" ||
              (role === "reviewer" && section !== "settings") ||
              (role === "auditor" &&
                (section === "overview" ||
                  section === "evidence" ||
                  section === "audit")),
          }}
        >
          <p>x</p>
        </AppShell>,
      );

    it("shows Administration and Case settings to a case admin", () => {
      open("case_admin");
      expect(screen.getByRole("link", { name: "Case settings" })).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /Tester/ }));
      expect(screen.getByRole("link", { name: "Administration" })).toBeInTheDocument();
    });

    it("hides Administration and Case settings from a reviewer", () => {
      open("reviewer");
      expect(screen.queryByRole("link", { name: "Case settings" })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /Tester/ }));
      expect(screen.queryByRole("link", { name: "Administration" })).not.toBeInTheDocument();
    });

    it("shows Audit but not Timeline to an auditor", () => {
      open("auditor");
      expect(screen.getByRole("link", { name: "Audit and exports" })).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "Timeline" })).not.toBeInTheDocument();
    });
  });

  it("renders a visible, localized failure when a verification action rejects", async () => {
    const onVerify = vi.fn().mockRejectedValue(new Error("private backend detail"));
    renderShell(onVerify);

    fireEvent.click(
      screen.getByRole("button", { name: "Open evidence details" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Verify now" }));

    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent("Verification failed.");
    expect(screen.queryByText("private backend detail")).not.toBeInTheDocument();
    expect(onVerify).toHaveBeenCalledWith(item);
  });
});
