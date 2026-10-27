import { Fragment, type ReactNode } from "react";
import { parseMarkdown, type Block, type Inline } from "../markdown/parse";

/**
 * Render model-generated markdown as React elements.
 *
 * Nothing here builds an HTML string: the parser returns data and this maps it
 * to elements, so text is escaped by React rather than by a function we wrote.
 * That is the whole safety argument, and it is why `dangerouslySetInnerHTML`
 * appears nowhere in this file.
 */

function renderInline(nodes: readonly Inline[]): ReactNode {
  return nodes.map((node, index) => {
    switch (node.kind) {
      case "text":
        return <Fragment key={index}>{node.value}</Fragment>;
      case "strong":
        return <strong key={index}>{renderInline(node.children)}</strong>;
      case "em":
        return <em key={index}>{renderInline(node.children)}</em>;
      case "code":
        return (
          <code key={index} className="markdown__code">
            {node.value}
          </code>
        );
      case "link":
        return (
          <a
            key={index}
            href={node.href}
            // A narrative that links out leaves the app: the new tab keeps the
            // case open behind it, and `noreferrer` keeps the case URL out of
            // whatever the link points at.
            target="_blank"
            rel="noreferrer noopener"
          >
            {node.text}
          </a>
        );
    }
  });
}

type HeadingTag = "h2" | "h3" | "h4" | "h5" | "h6";

function renderBlock(block: Block, key: number): ReactNode {
  switch (block.kind) {
    case "heading": {
      // The narrative's own numbering is content, not page structure, so a
      // summary's headings start at h2 and stop at h6: a generated summary must
      // not claim to be the page's h1.
      const level = Math.min(Math.max(block.level + 1, 2), 6);
      const Tag = `h${level}` as HeadingTag;
      return <Tag key={key}>{renderInline(block.content)}</Tag>;
    }
    case "paragraph":
      return <p key={key}>{renderInline(block.content)}</p>;
    case "list": {
      const items = block.items.map((item, index) => (
        <li key={index}>{renderInline(item)}</li>
      ));
      return block.ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>;
    }
    case "quote":
      return (
        <blockquote key={key}>
          {block.blocks.map((inner, index) => renderBlock(inner, index))}
        </blockquote>
      );
    case "code":
      return (
        <pre key={key} className="markdown__pre">
          <code>{block.value}</code>
        </pre>
      );
    case "rule":
      return <hr key={key} />;
  }
}

export function Markdown({
  source,
  className,
}: {
  source: string;
  className?: string;
}) {
  const blocks = parseMarkdown(source);
  return (
    <div className={`markdown${className ? ` ${className}` : ""}`}>
      {blocks.map((block, index) => renderBlock(block, index))}
    </div>
  );
}
