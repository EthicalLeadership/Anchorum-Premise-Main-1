import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { WarRoom } from "./WarRoom";

const chronology = {
  case_id: "c1",
  total_dated: 1,
  total_undated: 1,
  truncated: false,
  dated_entries: [
    {
      message_id: "m1",
      date: "2023-01-01T10:00:00Z",
      date_raw: null,
      from_address: "alice@example.com",
      to_address: "bob@example.com",
      subject: "Hello",
      thread_id: null,
    },
  ],
  undated_tray: [
    {
      message_id: "m2",
      date: null,
      date_raw: "Unknown Date",
      from_address: "bob@example.com",
      to_address: "alice@example.com",
      subject: null,
      thread_id: null,
    },
  ],
};

const actors = {
  case_id: "c1",
  total_messages: 1,
  unique_actors: 2,
  edges: [
    {
      from_address: "alice@example.com",
      to_address: "bob@example.com",
      count: 1,
    },
  ],
};

const gaps = {
  case_id: "c1",
  total: 0,
  gaps: [],
};

function mockFetch(map: Record<string, unknown>) {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    for (const [suffix, data] of Object.entries(map)) {
      if (url.endsWith(suffix)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: "OK",
          json: () => Promise.resolve(data),
        } as Response);
      }
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WarRoom", () => {
  it("renders board data from the three endpoints", async () => {
    mockFetch({
      "/chronology": chronology,
      "/actors": actors,
      "/gaps": gaps,
    });

    render(<WarRoom caseId="c1" locale="en" />);

    await waitFor(() => {
      expect(screen.getByTestId("war-room")).toBeInTheDocument();
    });

    // Chronology: dated entry and undated tray both surface their data
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    expect(screen.getByText("Unknown Date")).toBeInTheDocument();

    // Actors table row
    expect(screen.getAllByText("alice@example.com").length).toBeGreaterThan(0);

    // Gaps empty state
    expect(screen.getByTestId("war-room-gaps")).toBeInTheDocument();
  });

  it("shows truncation warning when the API flags truncation", async () => {
    mockFetch({
      "/chronology": { ...chronology, truncated: true },
      "/actors": actors,
      "/gaps": gaps,
    });

    render(<WarRoom caseId="c1" locale="en" />);

    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toBeInTheDocument();
    });
  });

  it("renders error state when a fetch fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.reject(new Error("network down")),
    );

    render(<WarRoom caseId="c1" locale="en" />);

    await waitFor(() => {
      expect(screen.queryByTestId("war-room")).not.toBeInTheDocument();
    });
  });
});
