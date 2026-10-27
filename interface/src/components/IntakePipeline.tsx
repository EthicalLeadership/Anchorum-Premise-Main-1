import type { IntakeStage } from "../adapter";
import { translate } from "../i18n";
import type { Locale } from "../types";

/**
 * The three stages a submitted email passes through, drawn in order.
 *
 * The stages come from the response rather than from a local constant, so what
 * is drawn is what ran. A stage the server did not reach is drawn as skipped,
 * never as pending: "we did not get there" and "we are still waiting" are
 * different facts and a reader deciding whether to resubmit needs the right one.
 */
const ORDER = ["received", "classified", "policy"] as const;
type StageId = (typeof ORDER)[number];

const STAGE_LABEL: Record<StageId, string> = {
  received: "email.intake.stage.received",
  classified: "email.intake.stage.classified",
  policy: "email.intake.stage.policy",
};

export function IntakePipeline({
  locale,
  stages,
}: {
  locale: Locale;
  stages: readonly IntakeStage[];
}) {
  const byId = new Map(stages.map((stage) => [stage.id, stage]));

  return (
    <ol className="intake-pipeline" aria-label={translate(locale, "email.intake.pipeline")}>
      {ORDER.map((id, index) => {
        const stage = byId.get(id);
        const status = stage?.status ?? "skipped";
        return (
          <li
            key={id}
            className="intake-pipeline__stage"
            data-stage={id}
            data-status={status}
          >
            <span className="intake-pipeline__marker" aria-hidden="true">
              {status === "success" ? "✓" : status === "failed" ? "!" : "–"}
            </span>
            <span className="intake-pipeline__name">
              {translate(locale, STAGE_LABEL[id] as never)}
            </span>
            <span className="intake-pipeline__detail">
              {stage?.detail ?? translate(locale, "email.intake.stage.not_reached")}
            </span>
            <span className="sr-only">
              {translate(locale, `email.intake.stage_status.${status}` as never)}
            </span>
            {index < ORDER.length - 1 ? (
              <span className="intake-pipeline__link" aria-hidden="true" />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
