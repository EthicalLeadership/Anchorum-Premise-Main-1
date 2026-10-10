import { useState } from "react";
import type { FormEvent } from "react";
import type { createAdapter } from "../adapter";
import { FormField } from "../components/FormField";
import { translate } from "../i18n";
import type { Locale } from "../types";
import en from "../../locales/en.json";

type MessageKey = keyof typeof en;

export interface CreateCaseProps {
  locale: Locale;
  adapter: ReturnType<typeof createAdapter>;
}

export function CreateCase({ locale, adapter }: CreateCaseProps) {
  const t = (key: MessageKey) => translate(locale, key);
  const [key, setKey] = useState("");
  const [title, setTitle] = useState("");
  const [jurisdiction, setJurisdiction] = useState("QC");
  const [matterType, setMatterType] = useState("labour");
  const [timezone, setTimezone] = useState("America/Montreal");
  const [description, setDescription] = useState("");
  const [keyError, setKeyError] = useState<string>();
  const [titleError, setTitleError] = useState<string>();
  const [banner, setBanner] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBanner(undefined);
    const required = t("case.create.error.required");
    const missingKey = key.trim() === "";
    const missingTitle = title.trim() === "";
    setKeyError(missingKey ? required : undefined);
    setTitleError(missingTitle ? required : undefined);
    if (missingKey || missingTitle) return;

    setBusy(true);
    const result = await adapter.cases.create({
      key: key.trim(),
      title: title.trim(),
      jurisdiction,
      matterType,
      timezone,
      description,
      memberIds: [],
    });
    setBusy(false);
    if (result.ok) {
      window.location.hash = `#/cases/${encodeURIComponent(result.value.id)}`;
      return;
    }
    if (result.error === "CASE_KEY_TAKEN") {
      setKeyError(t("case.create.error.key_taken"));
      return;
    }
    const errorKey = `error.${(result.error as string).toLowerCase()}`;
    setBanner(t(errorKey in en ? (errorKey as MessageKey) : "error.generic"));
  }

  return (
    <section className="create-case">
      <h1>{t("case.create.title")}</h1>
      {banner ? (
        <div className="create-case__banner" role="alert">
          {banner}
        </div>
      ) : null}
      <form noValidate aria-label={t("case.create.title")} onSubmit={submit}>
        <FormField
          id="case-key"
          label={t("case.create.field.key")}
          help={t("case.create.field.key_help")}
          value={key}
          onChange={setKey}
          error={keyError}
          required
        />
        <FormField
          id="case-title"
          label={t("case.create.field.title")}
          value={title}
          onChange={setTitle}
          error={titleError}
          required
        />
        <FormField
          id="case-jurisdiction"
          label={t("case.create.field.jurisdiction")}
          type="select"
          value={jurisdiction}
          onChange={setJurisdiction}
          options={[
            { value: "QC", label: t("case.create.option.jurisdiction.qc") },
            { value: "ON", label: t("case.create.option.jurisdiction.on") },
            { value: "CA", label: t("case.create.option.jurisdiction.ca") },
          ]}
        />
        <FormField
          id="case-matter-type"
          label={t("case.create.field.matter_type")}
          type="select"
          value={matterType}
          onChange={setMatterType}
          options={[
            { value: "labour", label: t("case.create.option.matter_type.labour") },
            { value: "civil", label: t("case.create.option.matter_type.civil") },
            {
              value: "commercial",
              label: t("case.create.option.matter_type.commercial"),
            },
          ]}
        />
        <FormField
          id="case-timezone"
          label={t("case.create.field.timezone")}
          value={timezone}
          onChange={setTimezone}
        />
        <FormField
          id="case-description"
          label={t("case.create.field.description")}
          type="textarea"
          value={description}
          onChange={setDescription}
        />
        <div className="create-case__actions">
          <button type="submit" className="btn btn--primary" disabled={busy}>
            {t("case.create.action.create")}
          </button>
          <a className="btn" href="#/cases">
            {t("case.create.action.cancel")}
          </a>
        </div>
      </form>
    </section>
  );
}
