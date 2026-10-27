/**
 * A small markdown parser for model output.
 *
 * The narrative this renders is generated text: untrusted in the same way any
 * model output is. It is parsed into an AST of plain data and rendered by React
 * as elements — never as an HTML string — so a narrative containing `<script>`
 * shows those characters and cannot become a tag.
 *
 * Only the constructs a legal narrative actually uses are supported: headings,
 * paragraphs, lists, quotes, code and rules; bold, italic, code and links.
 * Tables and images are deliberately absent — nothing here generates them, and
 * an unsupported syntax degrades to visible text rather than to nothing.
 */

export type Inline =
  | { kind: "text"; value: string }
  | { kind: "strong"; children: Inline[] }
  | { kind: "em"; children: Inline[] }
  | { kind: "code"; value: string }
  | { kind: "link"; href: string; text: string };

export type Block =
  | { kind: "heading"; level: number; content: Inline[] }
  | { kind: "paragraph"; content: Inline[] }
  | { kind: "list"; ordered: boolean; items: Inline[][] }
  | { kind: "quote"; blocks: Block[] }
  | { kind: "code"; value: string }
  | { kind: "rule" };

/** Link targets that reach a page rather than executing something. */
const SAFE_HREF = /^(https?:\/\/|mailto:|#|\/)/i;

/**
 * One pass over the inline syntax.
 *
 * The alternation order is the rule: a code span is consumed before emphasis so
 * that `*` inside backticks stays literal, and a link is consumed as a unit so
 * that `[a *b*](url)` does not lose its own brackets.
 */
const INLINE =
  /(`[^`]+`)|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*\n]+\*)|(_[^_\n]+_)|(\[[^\]]+\]\([^)\s]+\))/;

function parseLinkToken(token: string): Inline | null {
  const match = token.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
  if (!match) return null;
  const href = match[2];
  // A link whose scheme is not allowed is rendered as text. Returning null
  // rather than a link with a stripped href keeps the URL visible, so a reader
  // can see what the narrative tried to point at.
  if (!SAFE_HREF.test(href)) return null;
  return { kind: "link", href, text: match[1] };
}

export function parseInline(source: string): Inline[] {
  const nodes: Inline[] = [];
  let rest = source;

  while (rest.length > 0) {
    const match = INLINE.exec(rest);
    if (!match || match.index === undefined) {
      nodes.push({ kind: "text", value: rest });
      break;
    }
    if (match.index > 0) {
      nodes.push({ kind: "text", value: rest.slice(0, match.index) });
    }
    const token = match[0];
    rest = rest.slice(match.index + token.length);

    if (token.startsWith("`")) {
      nodes.push({ kind: "code", value: token.slice(1, -1) });
    } else if (token.startsWith("**") || token.startsWith("__")) {
      nodes.push({ kind: "strong", children: parseInline(token.slice(2, -2)) });
    } else if (token.startsWith("*") || token.startsWith("_")) {
      nodes.push({ kind: "em", children: parseInline(token.slice(1, -1)) });
    } else {
      const link = parseLinkToken(token);
      // Not a usable link: keep the characters so the reader sees them.
      nodes.push(link ?? { kind: "text", value: token });
    }
  }

  return nodes;
}

const HEADING = /^(#{1,6})\s+(.*)$/;
const RULE = /^(?:-{3,}|\*{3,}|_{3,})$/;
const UNORDERED = /^\s*[-*•]\s+(.*)$/;
const ORDERED = /^\s*\d+[.)]\s+(.*)$/;
const QUOTE = /^\s*>\s?(.*)$/;
const FENCE = /^\s*```/;

export function parseMarkdown(source: string): Block[] {
  const lines = (source ?? "").replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let index = 0;
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    blocks.push({
      kind: "paragraph",
      content: parseInline(paragraph.join(" ").trim()),
    });
    paragraph = [];
  };

  while (index < lines.length) {
    const line = lines[index];

    if (line.trim() === "") {
      flushParagraph();
      index += 1;
      continue;
    }

    if (FENCE.test(line)) {
      flushParagraph();
      const body: string[] = [];
      index += 1;
      while (index < lines.length && !FENCE.test(lines[index])) {
        body.push(lines[index]);
        index += 1;
      }
      // Skip the closing fence when there is one; an unterminated fence ends at
      // the end of the text rather than swallowing the rest of the render.
      index += 1;
      blocks.push({ kind: "code", value: body.join("\n") });
      continue;
    }

    if (RULE.test(line.trim())) {
      flushParagraph();
      blocks.push({ kind: "rule" });
      index += 1;
      continue;
    }

    const heading = line.match(HEADING);
    if (heading) {
      flushParagraph();
      blocks.push({
        kind: "heading",
        level: heading[1].length,
        content: parseInline(heading[2].trim()),
      });
      index += 1;
      continue;
    }

    if (QUOTE.test(line)) {
      flushParagraph();
      const inner: string[] = [];
      while (index < lines.length) {
        const next = lines[index].match(QUOTE);
        if (!next) break;
        inner.push(next[1]);
        index += 1;
      }
      blocks.push({ kind: "quote", blocks: parseMarkdown(inner.join("\n")) });
      continue;
    }

    if (UNORDERED.test(line) || ORDERED.test(line)) {
      flushParagraph();
      // Ordered-ness is decided by the first item and applied to the whole run.
      // A model that switches marker mid-list has still written one list;
      // splitting it in two would be a rendering artefact, not a distinction
      // the text makes. So every item is accepted — either marker keeps the run
      // going — while the *kind* of list was fixed by the first marker.
      const ordered = ORDERED.test(line);
      const items: Inline[][] = [];
      while (index < lines.length) {
        const match = lines[index].match(ORDERED) ?? lines[index].match(UNORDERED);
        if (!match) break;
        items.push(parseInline(match[1].trim()));
        index += 1;
      }
      blocks.push({ kind: "list", ordered, items });
      continue;
    }

    paragraph.push(line.trim());
    index += 1;
  }

  flushParagraph();
  return blocks;
}
