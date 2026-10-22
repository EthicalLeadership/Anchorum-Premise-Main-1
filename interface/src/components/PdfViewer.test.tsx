import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { PdfViewer } from "./PdfViewer";

// react-pdf renders through canvas, which jsdom does not implement. The mock
// stands in for the whole library so the test exercises PdfViewer's own state
// machine -- page clamping, zoom bounds, the failure branch -- and never the
// renderer. `Document` calls onLoadSuccess on mount so pageCount is populated
// the way the real component populates it.
vi.mock("react-pdf", async () => {
  const React = await import("react");
  type DocProps = {
    children?: React.ReactNode;
    loading?: React.ReactNode;
    onLoadSuccess?: (pdf: { numPages: number }) => void;
  };
  return {
    pdfjs: { GlobalWorkerOptions: {} },
    Document: ({ children, loading, onLoadSuccess }: DocProps) => {
      React.useEffect(() => {
        onLoadSuccess?.({ numPages: 3 });
      }, [onLoadSuccess]);
      return React.createElement(
        "div",
        { "data-testid": "pdf-document" },
        children ?? loading,
      );
    },
    Page: ({ pageNumber }: { pageNumber: number }) =>
      React.createElement(
        "div",
        { "data-testid": "pdf-page" },
        String(pageNumber),
      ),
  };
});

const FILE_URL = "/evidence/ev-42/download";

function renderViewer() {
  return render(<PdfViewer locale="en" fileUrl={FILE_URL} />);
}

describe("PdfViewer", () => {
  it("reports the page count once the document loads", () => {
    renderViewer();
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
  });

  it("starts on page 1 with the previous control disabled", () => {
    renderViewer();
    expect(screen.getByTestId("pdf-page")).toHaveTextContent("1");
    expect(screen.getByLabelText("Previous page")).toBeDisabled();
  });

  it("advances a page and stops at the last one", () => {
    renderViewer();
    const next = screen.getByLabelText("Next page");
    fireEvent.click(next);
    expect(screen.getByTestId("pdf-page")).toHaveTextContent("2");
    fireEvent.click(next);
    expect(screen.getByTestId("pdf-page")).toHaveTextContent("3");
    expect(next).toBeDisabled();
  });

  it("zooms within its bounds", () => {
    renderViewer();
    expect(screen.getByText("120%")).toBeInTheDocument();
    const zoomIn = screen.getByLabelText("Zoom in");
    for (let i = 0; i < 12; i += 1) fireEvent.click(zoomIn);
    expect(screen.getByText("300%")).toBeInTheDocument();

    const zoomOut = screen.getByLabelText("Zoom out");
    for (let i = 0; i < 20; i += 1) fireEvent.click(zoomOut);
    expect(screen.getByText("60%")).toBeInTheDocument();
  });

  it("offers the original file as a separate explicit download", () => {
    renderViewer();
    expect(screen.getByText("Download original file")).toHaveAttribute(
      "href",
      FILE_URL,
    );
  });
});
