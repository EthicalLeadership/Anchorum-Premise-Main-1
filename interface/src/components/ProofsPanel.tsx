import { useState } from "react";
import type { ProofsReport, createAdapter } from "../adapter";
import { formatDateTime, translate } from "../i18n";
import type { Locale } from "../types";

type Props = {
  locale: Locale;
  adapter: ReturnType<typeof createAdapter>;
  caseId: string;
  timeZone: string;
  /** Called after a successful run: the server records the verification as an
   *  audit row, so the log above this panel is now stale. */
  onVerified: () => void;
};

type Load =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "error"; key: string }
  | { kind: "ready"; report: ProofsReport };

/**
 * "Verify cryptographic proofs" — the results of re-deriving every claim the
 * case makes.
 *
 * The three outcomes are rendered differently on purpose. `not_checked` is not
 * a muted pass: a deployment with no signing key, or a host with no control
 * chain, has verified nothing, and a reader who sees a green tick against that
 * would be misled by the interface itself.
 */
export function ProofsPanel({ locale, adapter, caseId, timeZone, onVerified }: Props) {
  const [load, setLoad] = useState<Load>({ kind: "idle" });
  const t = (key: string, parameters?: Record<string, string | number>) =>
    translate(locale, key as never, parameters as never);

  async function run() {
    setLoad({ kind: "running" });
    const result = await adapter.audit.verifyProofs(caseId);
    if (!result.ok) {
      setLoad({ kind: "error", key: `proof.error.${result.error.toLowerCase()}` });
      return;
    }
    setLoad({ kind: "ready", report: result.value });
    onVerified();
  }

  return (
    <section className="proofs-panel" aria-labelledby="proofs-title" data-testid="proofs-panel">
      <h2 id="proofs-title">{t("proof.title")}</h2>
      <p className="proofs-panel__intro">{t("proof.intro")}</p>
      <button
        type="button"
        className="btn"
        onClick={run}
        disabled={load.kind === "running"}
      >
        {load.kind === "running" ? t("proof.action.running") : t("proof.action.verify")}
      </button>

      {load.kind === "error" ? (
        <p role="alert" className="form-error">{t(load.key)}</p>
      ) : null}

      {load.kind === "ready" ? (
        <>
          <p
            role="status"
            className={`proofs-panel__summary proofs-panel__summary--${load.report.status}`}
            data-testid="proofs-summary"
            data-status={load.report.status}
          >
            {t(`proof.summary.${load.report.status}`)}
            {" · "}
            {formatDateTime(locale, load.report.verifiedAt, timeZone)}
          </p>
          <ul className="proofs-panel__list">
            {load.report.proofs.map((proof) => (
              <li
                key={proof.id}
                className={`proofs-panel__item proofs-panel__item--${proof.status}`}
                data-status={proof.status}
              >
                <span className="proofs-panel__name">{t(`proof.title.${proof.id}`)}</span>
                <span className={`proofs-panel__status proofs-panel__status--${proof.status}`}>
                  {t(`proof.status.${proof.status}`)}
                </span>
                <span className="proofs-panel__detail">
                  {t(`proof.code.${proof.code}`)}
                  {proof.failingItem
                    ? ` ${t("proof.item.failed_at", { item: proof.failingItem })}`
                    : ""}
                </span>
              </li>
            ))}
          </ul>
          <p className="read-only">{t("proof.recorded")}</p>
        </>
      ) : null}
    </section>
  );
}
