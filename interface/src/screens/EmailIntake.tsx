import { useEffect, useState } from "react";
import type { createAdapter, EmailIntakeResult, IntakeFileResult } from "../adapter";
import { FileDropZone } from "../components/FileDropZone";
import { IntakeResultCard } from "../components/IntakeResultCard";
import { StateBlock } from "../components/StateBlock";
import { translate } from "../i18n";
import type { Locale } from "../types";

/**
 * Submit `.eml` files to the case's intake pipeline.
 *
 * The screen does one thing and shows one thing: what the pipeline decided
 * about each message. It does not summarise on the reader's behalf — a batch of
 * five where three passed and two were refused is five outcomes, and the screen
 * shows five.
 */
export function EmailIntake({
  locale,
  adapter,
  caseId,
}: {
  locale: Locale;
  adapter: ReturnType<typeof createAdapter>;
  caseId: string;
}) {
  const t = (key: string, parameters?: Record<string, string | number>) =>
    translate(locale, key as never, parameters);

  const [submitting, setSubmitting] = useState(false);
  const [pending, setPending] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<readonly IntakeFileResult[]>([]);
  const [summary, setSummary] = useState<EmailIntakeResult["summary"] | null>(null);
  const [timeZone, setTimeZone] = useState("UTC");

  // The case's own timezone, so a message's own date is shown in the court's
  // time rather than the browser's.
  useEffect(() => {
    let active = true;
    (async () => {
      const result = await adapter.cases.get(caseId);
      if (!active || !result.ok) return;
      setTimeZone(result.value.timezone || "UTC");
    })();
    return () => {
      active = false;
    };
  }, [adapter, caseId]);

  async function submit(files: File[]) {
    setSubmitting(true);
    setPending(files.length);
    setError(null);
    try {
      const payload = await Promise.all(
        files.map(async (file) => ({
          name: file.name,
          bytes: await file.arrayBuffer(),
        })),
      );
      const result = await adapter.cases.emailIntake(caseId, payload);
      if (!result.ok) {
        setError(
          result.error === "FEATURE_UNAVAILABLE"
            ? t("email.intake.error")
            : t("email.intake.error"),
        );
        return;
      }
      setResults(result.value.files);
      setSummary(result.value.summary);
    } finally {
      setSubmitting(false);
      setPending(0);
    }
  }

  return (
    <section className="email-intake">
      <h1>{t("email.intake.title")}</h1>
      <p>{t("email.intake.intro")}</p>

      <FileDropZone
        locale={locale}
        accept=".eml,message/rfc822"
        onFiles={(files) => void submit(files)}
      />
      <p className="email-intake__hint">{t("email.intake.dropzone_hint")}</p>

      {submitting ? (
        <p role="status">{t("email.intake.submitting", { count: pending })}</p>
      ) : null}

      {error ? (
        <p role="alert" className="form-error">
          {error}
        </p>
      ) : null}

      {summary ? (
        <p className="email-intake__summary" data-testid="intake-summary">
          {t("email.intake.summary", {
            processed: summary.processed,
            rejected: summary.rejectedPolicy,
            duplicate: summary.duplicate,
            failed: summary.failed,
          })}
        </p>
      ) : null}

      {results.length === 0 ? (
        submitting ? null : (
          <StateBlock locale={locale} kind="empty" message={t("email.intake.empty")} />
        )
      ) : (
        <div className="intake-results">
          {results.map((result, index) => (
            <IntakeResultCard
              key={`${result.filename}-${index}`}
              locale={locale}
              caseId={caseId}
              result={result}
              timeZone={timeZone}
            />
          ))}
        </div>
      )}
    </section>
  );
}
