import { useEffect, useRef } from "react";
import type { SummaryResult } from "../adapter";
import { formatDateTime, translate } from "../i18n";
import type { Locale } from "../types";
import { Markdown } from "./Markdown";

/**
 * The Saul narrative, in a panel that slides over the document.
 *
 * It is a drawer rather than a section of the page because the narrative is
 * about the document the reader is looking at, and reading it should not scroll
 * the document away. Being a panel it also has to behave like one: the close
 * button takes focus on open, Escape closes it, and the text behind it stays
 * where it was.
 *
 * The narrative renders as markdown; the claims below it render as a list,
 * because a claim is a statement with a quote and a verdict, and flattening the
 * three into a paragraph would hide the only part a reader can check.
 */
export function SaulSummaryDrawer({
  locale,
  open,
  loading,
  summary,
  timeZone,
  onClose,
}: {
  locale: Locale;
  open: boolean;
  loading: boolean;
  summary: SummaryResult | null;
  timeZone: string;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const t = (key: string, parameters?: Record<string, string | number>) =>
    translate(locale, key as never, parameters);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const narrative = summary?.narrative ?? null;
  const validation = summary?.validation ?? null;
  const reason = summary?.reason ?? "";

  return (
    <aside
      className="saul-drawer"
      role="dialog"
      aria-modal="false"
      aria-labelledby="saul-drawer-title"
    >
      <header className="saul-drawer__header">
        <h2 id="saul-drawer-title">{t("evidence.viewer.narrative_label")}</h2>
        <button
          ref={closeRef}
          type="button"
          className="saul-drawer__close"
          onClick={onClose}
          aria-label={t("evidence.viewer.summary.close")}
        >
          ×
        </button>
      </header>

      {loading ? (
        <p role="status">{t("evidence.viewer.summary.loading")}</p>
      ) : !summary ? (
        <p>{t("evidence.viewer.summary.empty")}</p>
      ) : reason === "NOT_GENERATED" ? (
        <p>{t("evidence.viewer.summary.not_generated")}</p>
      ) : reason === "LLM_DISABLED" ? (
        <p>{t("evidence.viewer.summary.disabled")}</p>
      ) : (
        <>
          {narrative?.error ? (
            <p role="alert" className="form-error">
              {t("evidence.viewer.summary.error", { error: narrative.error })}
            </p>
          ) : narrative?.narrative ? (
            <Markdown source={narrative.narrative} className="saul-drawer__narrative" />
          ) : (
            <p>{t("evidence.viewer.summary.empty")}</p>
          )}

          <dl className="saul-drawer__meta">
            <dt>{t("evidence.viewer.summary.model")}</dt>
            <dd className="mono">{narrative?.model ?? "—"}</dd>
            <dt>{t("evidence.viewer.summary.prompt")}</dt>
            <dd className="mono">{narrative?.prompt ?? "—"}</dd>
            {summary.generatedAt ? (
              <>
                <dt>{t("evidence.viewer.summary.generated_at")}</dt>
                <dd className="mono">
                  <time dateTime={summary.generatedAt}>
                    {formatDateTime(locale, summary.generatedAt, timeZone)}
                  </time>
                </dd>
              </>
            ) : null}
          </dl>

          {validation ? (
            <section
              className="saul-drawer__claims"
              aria-labelledby="saul-drawer-claims"
            >
              <h3 id="saul-drawer-claims">
                {t("evidence.viewer.summary.claims_title")}
              </h3>
              <p className="saul-drawer__counts">
                <span className="claim-count" data-claim-count="verified">
                  {t("evidence.viewer.summary.verified_count", {
                    count: validation.verified,
                  })}
                </span>
                <span className="claim-count" data-claim-count="inferred">
                  {t("evidence.viewer.summary.inferred_count", {
                    count: validation.inferred,
                  })}
                </span>
                <span className="claim-count" data-claim-count="rejected">
                  {t("evidence.viewer.summary.rejected_count", {
                    count: validation.rejected,
                  })}
                </span>
              </p>

              {validation.notRun ? (
                // Nothing was verified because nothing was produced. Saying so
                // is the honest report; three zeroes would read as a clean bill
                // of health for a summary that does not exist.
                <p role="alert" className="form-error">
                  {t("evidence.viewer.summary.not_run", { reason: validation.notRun })}
                </p>
              ) : null}

              {summary.claims.length > 0 ? (
                <ul className="claim-list">
                  {summary.claims.map((claim, index) => (
                    <li
                      key={index}
                      className="claim"
                      data-claim={claim.confidence}
                    >
                      <p className="claim__text">{claim.text}</p>
                      {claim.source.quote ? (
                        <blockquote className="claim__quote">
                          {claim.source.quote}
                        </blockquote>
                      ) : (
                        <p className="claim__inferred">
                          {t("evidence.viewer.summary.inferred_note")}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>{t("evidence.viewer.summary.claims_none")}</p>
              )}

              {validation.rejected_claims.length > 0 ? (
                <>
                  <h4>{t("evidence.viewer.summary.rejected_title")}</h4>
                  <ul className="claim-list claim-list--rejected">
                    {validation.rejected_claims.map((claim, index) => (
                      <li key={index} className="claim" data-claim="rejected">
                        <p className="claim__text">{claim.claim_text}</p>
                        <blockquote className="claim__quote">
                          {claim.attempted_quote}
                        </blockquote>
                        <p className="claim__reason" role="note">
                          {t("evidence.viewer.summary.rejected_reason", {
                            reason: claim.reason,
                          })}
                        </p>
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </section>
          ) : null}
        </>
      )}
    </aside>
  );
}
