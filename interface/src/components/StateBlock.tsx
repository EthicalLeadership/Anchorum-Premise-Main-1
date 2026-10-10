import { translate } from "../i18n";
import type { MessageKey } from "../i18n";
import type { Locale } from "../types";

interface StateBlockProps {
  locale: Locale;
  kind: "loading" | "empty" | "error" | "permission_limited";
  message?: string;
  action?: { label: string; href?: string; onClick?: () => void };
}

const defaults: Record<StateBlockProps["kind"], MessageKey> = {
  loading: "state.loading",
  empty: "state.empty",
  error: "state.error",
  permission_limited: "state.permission_limited",
};

export function StateBlock({ locale, kind, message, action }: StateBlockProps) {
  return (
    <div
      className={`state-block state-block--${kind}`}
      role={kind === "error" ? "alert" : "status"}
    >
      <p>{message ?? translate(locale, defaults[kind])}</p>
      {action?.href ? (
        <a className="btn btn--primary" href={action.href}>
          {action.label}
        </a>
      ) : action ? (
        <button type="button" className="btn" onClick={action.onClick}>
          {action.label}
        </button>
      ) : null}
    </div>
  );
}
