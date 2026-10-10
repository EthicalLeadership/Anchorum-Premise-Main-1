import type { TimelineEvent } from "../adapter";
import { translate } from "../i18n";
import type { Locale } from "../types";

type Props = {
  locale: Locale;
  caseId: string;
  event: TimelineEvent;
};

export function TimelineItem({ locale, caseId, event }: Props) {
  const t = (key: string, parameters?: Record<string, string | number>) =>
    translate(locale, key as never, parameters as never);

  return (
    <li className="timeline-item">
      <article>
        <p className="timeline-item__date">
          {event.date ?? t("timeline.date.unknown")}
        </p>
        <h2>{t(`timeline.event.${event.event}`)}</h2>
        <p>
          {t("timeline.people")}:{" "}
          {event.people
            .map((person) => t(`timeline.person.${person}`))
            .join(", ")}
        </p>
        <p>
          {t("timeline.date_precision.label")}:{" "}
          {t(`timeline.date_precision.${event.precision}`)}
        </p>
        <a
          href={`#/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(event.evidenceId)}`}
        >
          {t("timeline.source", { evidenceId: event.evidenceId })}
        </a>
      </article>
    </li>
  );
}
