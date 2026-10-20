import type { CustodyEntry } from "../adapter";
import { formatDateTime, translate } from "../i18n";
import type { Locale } from "../types";
import "../styles/chain-timeline.css";

type Props = {
  locale: Locale;
  entries: readonly CustodyEntry[];
  timeZone: string;
};

type ChainState = "linked" | "broken";

function stateOf(entry: CustodyEntry): ChainState {
  // Type-narrow defensively: the backend has been known to emit "not_checked"
  // for non-verification rows, but the frontend type is narrower. Anything
  // that is not explicitly "broken" is treated as linked for coloring; the
  // text label comes from t(`chain.${entry.chain}`) which will surface the
  // actual state value.
  return (entry.chain as string) === "broken" ? "broken" : "linked";
}

export function ChainTimeline({ locale, entries, timeZone }: Props) {
  if (entries.length === 0) return null;

  const t = (k: string) => translate(locale, k as never);
  const anyBroken = entries.some((e) => stateOf(e) === "broken");
  const overall: ChainState = anyBroken ? "broken" : "linked";

  return (
    <section
      className={`chain-timeline chain-timeline--${overall}`}
      data-testid="chain-timeline"
      data-state={overall}
      aria-labelledby="chain-timeline-title"
    >
      <h2 id="chain-timeline-title">{t("chain.timeline.title")}</h2>
      <ol className="chain-timeline__list">
        {entries.map((entry) => {
          const state = stateOf(entry);
          return (
            <li
              key={entry.id}
              className={`chain-timeline__step chain-timeline__step--${state}`}
              data-chain={entry.chain}
            >
              <span className="chain-timeline__marker" aria-hidden="true">
                {state === "broken" ? "\u2717" : "\u25CF"}
              </span>
              <div className="chain-timeline__body">
                <p className="chain-timeline__action">
                  {t(`custody.${entry.action}`)}
                </p>
                <p className="chain-timeline__meta">
                  {t(`custody.actor.${entry.actor}`)}
                  {" · "}
                  {formatDateTime(locale, entry.at, timeZone)}
                </p>
                <p className="chain-timeline__state">
                  {t(`chain.${entry.chain}`)}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
