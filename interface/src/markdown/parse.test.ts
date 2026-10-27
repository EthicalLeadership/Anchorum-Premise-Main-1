import { describe, expect, it } from "vitest";
import { parseInline, parseMarkdown } from "./parse";

describe("parseMarkdown", () => {
  it("reads headings with their level", () => {
    const blocks = parseMarkdown("## Faits établis");
    expect(blocks).toHaveLength(1);
    const heading = blocks[0];
    expect(heading.kind).toBe("heading");
    if (heading.kind !== "heading") return;
    expect(heading.level).toBe(2);
    expect(heading.content).toEqual([{ kind: "text", value: "Faits établis" }]);
  });

  it("keeps wrapped lines as one paragraph", () => {
    const blocks = parseMarkdown("Les prestations sont approuvées\njusqu'au 27 avril 2026.");
    expect(blocks).toHaveLength(1);
    if (blocks[0].kind !== "paragraph") throw new Error("expected a paragraph");
    expect(blocks[0].content).toEqual([
      {
        kind: "text",
        value: "Les prestations sont approuvées jusqu'au 27 avril 2026.",
      },
    ]);
  });

  it("splits a blank line into two paragraphs", () => {
    expect(parseMarkdown("un\n\ndeux")).toHaveLength(2);
  });

  it("collects a list and remembers whether it was ordered", () => {
    const unordered = parseMarkdown("- premier\n- second");
    expect(unordered[0].kind).toBe("list");
    if (unordered[0].kind !== "list") return;
    expect(unordered[0].ordered).toBe(false);
    expect(unordered[0].items).toHaveLength(2);

    const ordered = parseMarkdown("1. premier\n2. second");
    if (ordered[0].kind !== "list") throw new Error("expected a list");
    expect(ordered[0].ordered).toBe(true);
  });

  it("treats a marker change mid-list as one list", () => {
    // A model that writes "1." then "-" has written one list. Splitting it
    // would be a rendering artefact, not a distinction the text makes.
    const blocks = parseMarkdown("1. premier\n- second");
    expect(blocks).toHaveLength(1);
    if (blocks[0].kind !== "list") throw new Error("expected a list");
    expect(blocks[0].items).toHaveLength(2);
  });

  it("parses a blockquote, fenced code and a rule", () => {
    const blocks = parseMarkdown("> noté\n\n```\nx = 1\n```\n\n---");
    expect(blocks.map((block) => block.kind)).toEqual(["quote", "code", "rule"]);
    if (blocks[1].kind !== "code") return;
    expect(blocks[1].value).toBe("x = 1");
  });

  it("ends an unterminated fence at the end of the text", () => {
    const blocks = parseMarkdown("```\njamais fermé");
    expect(blocks).toHaveLength(1);
    if (blocks[0].kind !== "code") throw new Error("expected code");
    expect(blocks[0].value).toBe("jamais fermé");
  });

  it("keeps a citation bracket as text, not a link", () => {
    const blocks = parseMarkdown(
      "Les prestations courent jusqu'en 2026 [source: note.txt, page 1].",
    );
    if (blocks[0].kind !== "paragraph") throw new Error("expected a paragraph");
    const text = blocks[0].content
      .map((node) => (node.kind === "text" ? node.value : ""))
      .join("");
    expect(text).toContain("[source: note.txt, page 1]");
    expect(blocks[0].content.some((node) => node.kind === "link")).toBe(false);
  });
});

describe("parseInline", () => {
  it("reads bold, italic and inline code", () => {
    expect(parseInline("**gras** et *italique* et `code`")).toEqual([
      { kind: "strong", children: [{ kind: "text", value: "gras" }] },
      { kind: "text", value: " et " },
      { kind: "em", children: [{ kind: "text", value: "italique" }] },
      { kind: "text", value: " et " },
      { kind: "code", value: "code" },
    ]);
  });

  it("leaves the asterisks inside a code span alone", () => {
    expect(parseInline("`a * b * c`")).toEqual([
      { kind: "code", value: "a * b * c" },
    ]);
  });

  it("accepts http, mailto and relative links", () => {
    expect(parseInline("[ici](https://exemple.ca)")).toEqual([
      { kind: "link", href: "https://exemple.ca", text: "ici" },
    ]);
    expect(parseInline("[nous](/aide)")).toEqual([
      { kind: "link", href: "/aide", text: "nous" },
    ]);
  });

  it("refuses a javascript: link but keeps its characters visible", () => {
    // The URL stays on screen rather than silently losing its target: a reader
    // is entitled to see what the narrative tried to point at.
    const nodes = parseInline("[cliquez](javascript:alert(1))");
    expect(nodes.some((node) => node.kind === "link")).toBe(false);
    const text = nodes.map((node) => (node.kind === "text" ? node.value : "")).join("");
    expect(text).toContain("javascript:alert(1)");
  });

  it("does not turn a bare angle-bracket tag into an element", () => {
    // Nothing in this parser produces HTML: a script tag in the model's output
    // is characters, and React escapes them when it renders.
    expect(parseInline("<script>alert(1)</script>")).toEqual([
      { kind: "text", value: "<script>alert(1)</script>" },
    ]);
  });
});
