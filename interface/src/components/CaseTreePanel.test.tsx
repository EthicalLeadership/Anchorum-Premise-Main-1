// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { createAdapter } from "../adapter";
import { CaseTreePanel } from "./CaseTreePanel";
import { fixture } from "../fixtures/dupont-v-acme";

afterEach(cleanup);

describe("CaseTreePanel", () => {
  it("lists existing cases", async () => {
    const adapter = createAdapter({ backend: null });
    render(<CaseTreePanel locale="en" adapter={adapter} />);
    const key = await screen.findByText(fixture.case.key);
    expect(key).toBeTruthy();
    expect(screen.getByText(fixture.case.title)).toBeTruthy();
  });

  it("calls ingest with the selected category and source", async () => {
    const adapter = createAdapter({ backend: null });
    const ingestSpy = vi.spyOn(adapter.evidence, "ingest");

    render(<CaseTreePanel locale="en" adapter={adapter} />);
    await screen.findByText(fixture.case.key);

    const selects = screen.getAllByRole("combobox") as HTMLSelectElement[];
    fireEvent.change(selects[0], { target: { value: "medical" } });
    fireEvent.change(selects[1], { target: { value: "clinic" } });

    const input = document.querySelector(
      ".case-tree__upload input[type=file]",
    ) as HTMLInputElement;
    expect(input).toBeTruthy();

    const file = new File([new Uint8Array([1, 2, 3])], "tree-upload-test.txt", {
      type: "text/plain",
    });
    Object.defineProperty(file, "arrayBuffer", {
      value: () => Promise.resolve(new ArrayBuffer(3)),
    });
    Object.defineProperty(input, "files", {
      value: [file],
      configurable: true,
    });

    fireEvent.change(input);

    await waitFor(() => {
      expect(ingestSpy).toHaveBeenCalledWith(
        fixture.case.id,
        expect.objectContaining({
          name: "tree-upload-test.txt",
          category: "medical",
          source: "clinic",
        }),
      );
    });
  });
});
