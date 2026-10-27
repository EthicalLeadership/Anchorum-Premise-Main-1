import { useEffect, useState } from "react";
import type { AnchorState, createAdapter } from "../adapter";
import { formatDateTime, translate } from "../i18n";
import type { Locale } from "../types";
import "../styles/anchor-panel.css";

type Props = {
  locale: Locale;
  adapter: ReturnType<typeof createAdapter>;
  caseId: string;
  /** The case's timezone, so a publication time reads on the reader's clock. */
  timeZone?: string;
};

type Load =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; state: AnchorState };

/** Enough of a digest to compare by eye, with the whole value on the element. */
function shortDigest(value?: string): string {
  if (!value) return "";
  return value.length > 20 ? `${value.slice(0, 20)}…` : value;
}

export function AnchorPanel({ locale, adapter, caseId, timeZone }: Props) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const t = (key: string, parameters?: Record<string, string | number>) =>
    translate(locale, key as never, parameters as never);

  useEffect(() => {
    let active = true;
    adapter.anchoring.get(caseId).then((result) => {
      if (!active) return;
      setLoad(
        result.ok
          ? { kind: "ready", state: result.value }
          : { kind: "error", message: translate(locale, `error.${result.error.toLowerCase()}` as never) },
      );
    });
    return () => {
      active = false;
    };
  }, [adapter, caseId, locale]);

  async function onPublish() {
    setBusy(true);
    setFailure(null);
    const result = await adapter.anchoring.publish(caseId);
    setBusy(false);
    if (!result.ok) {
      setFailure(t(`anchor.error.${result.error.toLowerCase()}`));
      return;
    }
    setLoad({ kind: "ready", state: result.value });
  }

  if (load.kind === "loading") {
    return (
      <section className="anchor-panel" aria-busy="true">
        <h2>{t("anchor.title")}</h2>
        <p>{t("state.loading")}</p>
      </section>
    );
  }
  if (load.kind === "error") {
    return (
      <section className="anchor-panel">
        <h2>{t("anchor.title")}</h2>
        <p role="alert">{load.message}</p>
      </section>
    );
  }

  const state = load.state;
  const published = state.anchored === true;
  return (
    <section className="anchor-panel" aria-labelledby="anchor-title">
      <h2 id="anchor-title">{t("anchor.title")}</h2>
      <p className="anchor-panel__help">{t("anchor.help")}</p>

      {published ? (
        <dl className="anchor-panel__facts">
          <dt>{t("anchor.record_name")}</dt>
          <dd className="anchor-panel__mono">{state.recordName}</dd>
          <dt>{t("anchor.digest")}</dt>
          <dd className="anchor-panel__mono" title={state.digest}>
            {shortDigest(state.digest)}
          </dd>
          {state.publishedAt ? (
            <>
              <dt>{t("anchor.published_at")}</dt>
              <dd>{formatDateTime(locale, state.publishedAt, timeZone ?? "UTC")}</dd>
            </>
          ) : null}
        </dl>
      ) : (
        <p className="anchor-panel__status">
          {t("anchor.not_anchored", { name: state.expectedName ?? "" })}
        </p>
      )}

      {/* Published and current digests are shown together on purpose: a reader
          told "anchored" can check nothing, a reader shown two digests can. */}
      {published && state.stale ? (
        <p role="alert" className="anchor-panel__stale">
          {t("anchor.stale", {
            published: shortDigest(state.digest),
            current: shortDigest(state.currentDigest),
          })}
        </p>
      ) : null}

      {!state.configured ? (
        <p className="anchor-panel__hint">{t("anchor.not_configured")}</p>
      ) : null}

      <div className="anchor-panel__actions">
        <button
          type="button"
          className="btn btn--primary"
          disabled={busy || !state.configured}
          onClick={onPublish}
        >
          {busy
            ? t("anchor.publishing")
            : published
              ? t("anchor.action.republish")
              : t("anchor.action.publish")}
        </button>
      </div>
      {failure ? (
        <p role="alert" className="form-error">
          {failure}
        </p>
      ) : null}
    </section>
  );
}
