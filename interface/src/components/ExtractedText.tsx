import { useEffect, useRef } from "react";
import { translate } from "../i18n";
import type { EvidenceText } from "../adapter";
import type { Locale } from "../types";

/** Where a search hit landed: character offset plus the term that matched. */
export type Highlight = { at: number; term: string };

type Props = {
  locale: Locale;
  text: EvidenceText;
  highlight?: Highlight | null;
};

/**
 * The text analysis extracted from one artifact.
 *
 * Every branch here keeps one distinction visible: a document nobody read is
 * not an empty document. `status` is `unsupported` when the connector has no
 * reader for the file type, `empty` when it read the bytes and found no text,
 * `skipped_oversize` when it refused on size, `failed` when the read did not
 * complete, and `stored` when analysis never ran. Showing a blank pane for all
 * five would tell a lawyer their exhibit is blank.
 */
export function ExtractedText({ locale, text, highlight }: Props) {
  const t = (k: string, parameters?: Record<string, string | number>) =>
    translate(locale, k as never, parameters);

  // Hooks come first and unconditionally: the null-text branch returns early,
  // and a hook declared after it would run on some renders and not others.
  const body = text.text ?? "";
  // The offset is clamped to what is actually here: a hit beyond the
  // 200,000-character cap cannot be shown, and marking the wrong characters
  // would be worse than marking none.
  const markStart =
    text.text !== null && highlight && highlight.term.length > 0
      ? Math.min(Math.max(highlight.at, 0), body.length)
      : -1;
  const markEnd =
    markStart >= 0 ? Math.min(markStart + highlight!.term.length, body.length) : -1;
  const markRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    // Optional call: the method is absent in jsdom and in any older engine,
    // and a missing scroll is not worth throwing a render away.
    markRef.current?.scrollIntoView?.({ block: "center" });
  }, [markStart]);

  if (text.text === null) {
    // One message per status, because each is a different fact about the file.
    const reasonKey =
      text.status === "stored"
        ? "evidence.text.not_analysed"
        : `evidence.intake.result.${text.status}`;
    return (
      <p role="status" className="extracted-text extracted-text--none">
        {t(reasonKey)}
      </p>
    );
  }

  return (
    <div className="extracted-text">
      <p className="extracted-text__meta">
        {t("evidence.text.chars", { count: text.chars })}
        {text.truncated ? ` · ${t("evidence.text.truncated")}` : ""}
      </p>
      <pre className="extracted-text__body">
        {markStart < 0 ? (
          body
        ) : (
          <>
            {body.slice(0, markStart)}
            <mark className="extracted-text__hit" ref={markRef}>
              {body.slice(markStart, markEnd)}
            </mark>
            {body.slice(markEnd)}
          </>
        )}
      </pre>
    </div>
  );
}
