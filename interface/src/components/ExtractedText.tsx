import { translate } from "../i18n";
import type { EvidenceText } from "../adapter";
import type { Locale } from "../types";

type Props = {
  locale: Locale;
  text: EvidenceText;
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
export function ExtractedText({ locale, text }: Props) {
  const t = (k: string, parameters?: Record<string, string | number>) =>
    translate(locale, k as never, parameters);

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
      <pre className="extracted-text__body">{text.text}</pre>
    </div>
  );
}
