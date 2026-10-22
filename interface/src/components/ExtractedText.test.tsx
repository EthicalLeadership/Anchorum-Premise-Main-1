import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ExtractedText } from "./ExtractedText";
import { translate } from "../i18n";

const base = {
  id: "E-1",
  sha256: "abc",
  truncated: false,
};

describe("ExtractedText", () => {
  it("renders the extracted text and its character count", () => {
    render(
      <ExtractedText
        locale="en"
        text={{
          ...base,
          status: "extracted",
          chars: 42,
          reason: "",
          text: "Lumbar disc herniation at L4-L5.",
        }}
      />,
    );
    expect(screen.getByText("Lumbar disc herniation at L4-L5.")).toBeInTheDocument();
    expect(screen.getByText("42 characters extracted")).toBeInTheDocument();
  });

  it("says when the text was truncated rather than showing a silent cut", () => {
    render(
      <ExtractedText
        locale="en"
        text={{
          ...base,
          status: "extracted",
          chars: 200000,
          reason: "",
          text: "a".repeat(10),
          truncated: true,
        }}
      />,
    );
    expect(
      screen.getByText(/showing the first 200,000 characters only/),
    ).toBeInTheDocument();
  });

  it("explains an unread format instead of showing a blank pane", () => {
    render(
      <ExtractedText
        locale="en"
        text={{
          ...base,
          status: "unsupported",
          chars: 0,
          reason: "Word documents (.docx) have no reader",
          text: null,
        }}
      />,
    );
    // The message must name the reason, not merely report emptiness.
    expect(
      screen.getByText(translate("en", "evidence.intake.result.unsupported")),
    ).toBeInTheDocument();
  });

  it("distinguishes 'not analysed yet' from 'not readable'", () => {
    render(
      <ExtractedText
        locale="en"
        text={{
          ...base,
          status: "stored",
          chars: 0,
          reason: "",
          text: null,
        }}
      />,
    );
    expect(
      screen.getByText(translate("en", "evidence.text.not_analysed")),
    ).toBeInTheDocument();
  });

  it("reports an empty read as an empty read", () => {
    render(
      <ExtractedText
        locale="en"
        text={{
          ...base,
          status: "empty",
          chars: 0,
          reason: "artifact produced no text",
          text: null,
        }}
      />,
    );
    expect(
      screen.getByText(translate("en", "evidence.intake.result.empty")),
    ).toBeInTheDocument();
  });
});
