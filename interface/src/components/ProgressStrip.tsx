import { translate } from "../i18n";
import type { Locale } from "../types";

export const INTAKE_STAGES = ["received", "preserved", "scanned", "indexed"] as const;
export type IntakeState = "pending" | "active" | "done" | "failed" | "quarantined";

interface Props {
  locale: Locale;
  state: IntakeState;
  failedStage?: (typeof INTAKE_STAGES)[number];
}

export function ProgressStrip({ locale, state, failedStage }: Props) {
  const reached = state === "done" ? 4 : state === "pending" ? 0 : state === "active" ? 1 : 2;
  const failedIndex = failedStage ? INTAKE_STAGES.indexOf(failedStage) : -1;
  return (
    <div className="progress-strip" data-state={state}>
      <ol>
        {INTAKE_STAGES.map((stage, i) => (
          <li key={stage} data-done={i < reached && i !== failedIndex} data-failed={failedStage === stage}>
            {translate(locale, `evidence.intake.stage.${stage}` as never)}
          </li>
        ))}
      </ol>
      <span>{translate(locale, `evidence.intake.state.${state}` as never)}</span>
      {state === "failed" && failedStage ? (
        <p role="alert">
          {translate(locale, "evidence.intake.error", {
            step: translate(locale, `evidence.intake.stage.${failedStage}` as never),
          })}
        </p>
      ) : null}
    </div>
  );
}
