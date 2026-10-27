import type { IntakeFileResult } from "../adapter";
import { formatDateTime, translate } from "../i18n";
import type { Locale } from "../types";
import { IntakePipeline } from "./IntakePipeline";

/**
 * One submitted message and what became of it.
 *
 * The verdict is stated in words and repeated in a data attribute, not carried
 * by colour alone: a rejected message that only looks different from a
 * processed one is invisible to a reader who cannot see the difference.
 */
export function IntakeResultCard({
  locale,
  caseId,
  result,
  timeZone,
}: {
  locale: Locale;
  caseId: string;
  result: IntakeFileResult;
  timeZone: string;
}) {
  const t = (key: string, parameters?: Record<string, string | number>) =>
    translate(locale, key as never, parameters);

  const verdictClass =
    result.status === "processed"
      ? "intake-card--processed"
      : result.status === "rejected_policy"
        ? "intake-card--rejected"
        : result.status === "duplicate"
          ? "intake-card--duplicate"
          : "intake-card--failed";

  return (
    <article
      className={`intake-card ${verdictClass}`}
      data-intake-status={result.status}
    >
      <header className="intake-card__header">
        <h3 className="intake-card__filename">{result.filename}</h3>
        <span className="intake-card__verdict">
          {t(`email.intake.result.${result.status}`)}
        </span>
      </header>

      <dl className="intake-card__meta">
        <dt>{t("email.intake.column.subject")}</dt>
        <dd>{result.subject || t("evidence.intake.unset")}</dd>
        <dt>{t("email.intake.column.sender")}</dt>
        <dd className="mono">{result.sender || t("evidence.intake.unset")}</dd>
        {result.date ? (
          <>
            <dt>{t("email.intake.actor")}</dt>
            <dd>{result.actor || t("evidence.intake.unset")}</dd>
            <dt>{t("email.intake.confidence")}</dt>
            <dd className="mono">
              {typeof result.confidence === "number"
                ? result.confidence.toFixed(2)
                : "—"}
            </dd>
            <dt>{t("audit.column.time")}</dt>
            <dd className="mono">
              <time dateTime={result.date}>
                {formatDateTime(locale, result.date, timeZone)}
              </time>
            </dd>
          </>
        ) : null}
        {typeof result.attachmentCount === "number" && result.attachmentCount > 0 ? (
          <>
            <dt>{t("email.intake.attachments")}</dt>
            <dd className="mono">{result.attachmentCount}</dd>
          </>
        ) : null}
      </dl>

      <IntakePipeline locale={locale} stages={result.stages} />

      {result.policy ? (
        <p
          className={
            result.policy.allowed === false
              ? "intake-card__policy intake-card__policy--denied"
              : "intake-card__policy"
          }
        >
          {result.policy.allowed === false
            ? t("email.intake.policy_rejected", { reason: result.policy.reason })
            : t("email.intake.policy_allowed")}
          {result.policy.quarantine ? ` · ${t("email.intake.quarantine")}` : ""}
        </p>
      ) : null}

      {result.labels && result.labels.length > 0 ? (
        <p className="intake-card__labels">
          <span>{t("email.intake.labels")}: </span>
          {result.labels.join(", ")}
        </p>
      ) : null}

      {result.reason ? (
        <p role="alert" className="form-error">
          {result.reason}
        </p>
      ) : null}

      {result.evidenceId && caseId ? (
        <p>
          <a
            href={`#/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(
              result.evidenceId,
            )}`}
          >
            {t("email.intake.open_evidence")}
          </a>
        </p>
      ) : null}
    </article>
  );
}
