// @vitest-environment jsdom
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { createAdapter } from "../adapter";
import { translate } from "../i18n";
import { CreateCase } from "./CreateCase";

afterEach(cleanup);

function fill(key: string, title: string) {
  fireEvent.change(document.getElementById("case-key")!, { target: { value: key } });
  fireEvent.change(document.getElementById("case-title")!, { target: { value: title } });
  fireEvent.submit(screen.getByRole("form"));
}

describe("CreateCase", () => {
  it("renders the form", () => {
    render(<CreateCase locale="en" adapter={createAdapter({ backend: null })} />);
    expect(screen.getByRole("form")).toBeTruthy();
  });

  it("shows key_taken as a field error", async () => {
    render(<CreateCase locale="en" adapter={createAdapter({ backend: null })} />);
    fill("CASE-2024-018", "Dup");
    await waitFor(() =>
      expect(
        screen.getByText(translate("en", "case.create.error.key_taken")),
      ).toBeTruthy(),
    );
  });

  it("requires key and title", () => {
    render(<CreateCase locale="en" adapter={createAdapter({ backend: null })} />);
    fireEvent.submit(screen.getByRole("form"));
    expect(screen.getAllByText(translate("en", "case.create.error.required"))).toHaveLength(2);
  });

  it("redirects on success", async () => {
    render(<CreateCase locale="en" adapter={createAdapter({ backend: null })} />);
    fill("CASE-NEW-1", "New");
    await waitFor(() => expect(window.location.hash).toMatch(/^#\/cases\/case-/));
  });

  it("renders a banner for backend errors", async () => {
    render(
      <CreateCase
        locale="en"
        adapter={createAdapter({ backend: { baseUrl: "http://invalid.invalid" } })}
      />,
    );
    fill("CASE-X", "X");
    await waitFor(() =>
      expect(
        screen.getByText(translate("en", "error.backend_unreachable")),
      ).toBeTruthy(),
    );
  });
});
