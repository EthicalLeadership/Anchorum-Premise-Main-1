import { translate, formatDateTime } from "../i18n";
import type { Locale } from "../types";

export type VerificationStep = { id: string; result: string };
export type VerificationView = {
  result: string;
  verifiedAt: string;
  failingStep?: string | null;
  steps: readonly VerificationStep[];
};

type Props = {
  locale: Locale;
  timeZone: string;
  verification: VerificationView;
};

export function VerificationTile({ locale, timeZone, verification }: Props) {
  const failingId = verification.steps.find((s) => s.result === "fail")?.id;
  return (
    <section className="verification-tile" aria-labelledby="verification-title">
      <h2 id="verification-title">{translate(locale, "overview.integrity.title")}</h2>
      <div className="verification-segments" aria-hidden="true">
        {verification.steps.map((s) => (
          <span key={s.id} className={`segment segment-${s.result}`} />
        ))}
      </div>
      <ul className="verification-steps">
        {verification.steps.map((s) => {
          const ok = s.result === "pass";
          return (
            <li key={s.id} className={ok ? "step-pass" : "step-fail"}>
              <span aria-hidden="true">{ok ? "✓" : "✗"}</span>{" "}
              <span>{translate(locale, `overview.integrity.step.${s.id}` as never)}</span>
              {": "}
              <span>{translate(locale, ok ? "verification.pass" : "verification.fail")}</span>
            </li>
          );
        })}
      </ul>
      {failingId ? (
        <p role="alert" className="verification-failing">
          {translate(locale, "verification.failing_step", {
            step: translate(
              locale,
              `overview.integrity.step.${failingId}` as never,
            ),
          })}
          {verification.failingStep
            ? ` ${translate(locale, `reason.${verification.failingStep}` as never)}`
            : ""}
        </p>
      ) : null}
      <p className="verification-when">
        {translate(locale, "overview.integrity.verified_at", {
          when: formatDateTime(locale, verification.verifiedAt, timeZone),
        })}
      </p>
    </section>
  );
}
