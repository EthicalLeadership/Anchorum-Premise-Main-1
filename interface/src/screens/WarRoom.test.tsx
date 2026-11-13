import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { createAdapter } from "../adapter";
import type { Finding } from "../types";
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

const findings = [] as Finding[];

function mockAdapter(failed = false) {
  const result = <T,>(value: T) =>
    failed ? { ok: false as const, error: "HTTP_500" } : { ok: true as const, value };

  return {
    board: {
      chronology: vi.fn(async () => result(chronology)),
      actors: vi.fn(async () => result(actors)),
      gaps: vi.fn(async () => result(gaps)),
      findings: vi.fn(async () => result(findings)),
      updateFinding: vi.fn(async (_cid, fid, status) => {
        return result({ id: fid, status });
      }),
    },
  } as unknown as Pick<ReturnType<typeof createAdapter>, "board">;
}

afterEach(() => {
  vi.restoreAllMocks();
});

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("/anchor/verify")) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: () => Promise.resolve({ detail: "not found" }),
        } as unknown as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
      } as unknown as Response);
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WarRoom", () => {
  it("renders board data from the three endpoints", async () => {
    render(<WarRoom caseId="c1" locale="en" adapter={mockAdapter()} />);

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
    const adapter = mockAdapter();
    vi.mocked(adapter.board.chronology).mockResolvedValue({
      ok: true,
      value: { ...chronology, truncated: true },
    });

    render(<WarRoom caseId="c1" locale="en" adapter={adapter} />);

    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toBeInTheDocument();
    });
  });

  it("renders error state when a fetch fails", async () => {
    render(<WarRoom caseId="c1" locale="en" adapter={mockAdapter(true)} />);

    // The container is always present so the route test can mount-find it.
    // The error state lives inside the container as an alert.
    const container = await screen.findByTestId("war-room");
    expect(container).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
