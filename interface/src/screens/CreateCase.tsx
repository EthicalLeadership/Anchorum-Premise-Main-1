import { useState } from "react";
import type { FormEvent } from "react";
import type { createAdapter } from "../adapter";
import { FileDropZone } from "../components/FileDropZone";
import { CaseTreePanel } from "../components/CaseTreePanel";
import { FormField } from "../components/FormField";
import { translate } from "../i18n";
import type { Locale } from "../types";
import en from "../../locales/en.json";

type MessageKey = keyof typeof en;

export interface CreateCaseProps {
  locale: Locale;
  adapter: ReturnType<typeof createAdapter>;
}

interface QueuedFile {
  file: File;
  status: "queued" | "uploading" | "done" | "failed";
  error?: string;
}

/**
 * Create a case and, in the same action, attach any files the user dropped.
 *
 * The two steps are ordered and visible: the case is created first, because
 * an artifact cannot belong to a case that does not yet exist; then each
 * file is uploaded, one at a time, so a failure is attributed to a named
 * file and not to "the upload." A partial success is a real outcome, so it
 * is shown as one rather than being rolled back: the case exists, some
 * files are in it, and the ones that failed are named.
 */
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
  const [queued, setQueued] = useState<QueuedFile[]>([]);
  // Set once the case exists, so a retry does not try to create it twice.
  const [createdCaseId, setCreatedCaseId] = useState<string | null>(null);

  const addFiles = (files: File[]) =>
    setQueued((all) => [
      ...all,
      ...files.map((f) => ({ file: f, status: "queued" as const })),
    ]);

  const removeFile = (i: number) =>
    setQueued((all) => all.filter((_, idx) => idx !== i));

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBanner(undefined);

    // If the case was already created and there is nothing new to upload,
    // go straight to the evidence page. If new files have been queued since,
    // fall through so they upload against the existing case.
    if (createdCaseId !== null && queued.every((q) => q.status === "done")) {
      window.location.hash = `#/cases/${encodeURIComponent(createdCaseId)}/evidence`;
      return;
    }

    const required = t("case.create.error.required");
    const missingKey = key.trim() === "";
    const missingTitle = title.trim() === "";
    setKeyError(missingKey ? required : undefined);
    setTitleError(missingTitle ? required : undefined);
    if (missingKey || missingTitle) return;

    setBusy(true);

    // Step 1: create the case, unless it already exists (then this submit is
    // uploading additional files against it).
    let caseId: string;
    if (createdCaseId !== null) {
      caseId = createdCaseId;
    } else {
      const result = await adapter.cases.create({
        key: key.trim(),
        title: title.trim(),
        jurisdiction,
        matterType,
        timezone,
        description,
        memberIds: [],
      });
      if (!result.ok) {
        setBusy(false);
        if (result.error === "CASE_KEY_TAKEN") {
          setKeyError(t("case.create.error.key_taken"));
          return;
        }
        const errorKey = `error.${(result.error as string).toLowerCase()}`;
        setBanner(t(errorKey in en ? (errorKey as MessageKey) : "error.generic"));
        return;
      }
      caseId = result.value.id;
      setCreatedCaseId(caseId);
    }

    // Step 2: upload each queued file. A failure is recorded against the
    // file, not thrown; the loop continues so one bad PDF does not hide the
    // state of the others.
    const failures: string[] = [];
    for (let i = 0; i < queued.length; i++) {
      const qf = queued[i];
      setQueued((all) =>
        all.map((row, idx) =>
          idx === i ? { ...row, status: "uploading" } : row,
        ),
      );
      try {
        const bytes = await qf.file.arrayBuffer();
        const r = await adapter.evidence.ingest(caseId, {
          name: qf.file.name,
          size: qf.file.size,
          type: qf.file.type,
          bytes,
        });
        if (r.ok) {
          setQueued((all) =>
            all.map((row, idx) =>
              idx === i ? { ...row, status: "done" } : row,
            ),
          );
        } else {
          const msg = String(r.error ?? "unknown");
          failures.push(`${qf.file.name}: ${msg}`);
          setQueued((all) =>
            all.map((row, idx) =>
              idx === i ? { ...row, status: "failed", error: msg } : row,
            ),
          );
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        failures.push(`${qf.file.name}: ${msg}`);
        setQueued((all) =>
          all.map((row, idx) =>
            idx === i ? { ...row, status: "failed", error: msg } : row,
          ),
        );
      }
    }

    setBusy(false);

    // Step 3: navigate if everything landed. If any file failed, stay here
    // and name them; the reader decides whether to fix and retry or go on.
    if (failures.length === 0) {
      window.location.hash = `#/cases/${encodeURIComponent(caseId)}/evidence`;
      return;
    }
    setBanner(
      `Case ${caseId} created. ${failures.length} of ${queued.length} file(s) ` +
        `could not be read -- ${failures.join("; ")}. Click Continue to open ` +
        `the case; the failed files are not attached.`,
    );
  }

  // Only lock the form while an upload is actively running. Once the case
  // exists, the user can still add more files (each posts to the same case)
  // or clear the list.
  const uploading = busy;
  const pending = queued.filter((q) => q.status !== "done").length;

  return (
    <section className="create-case">
      <div className="create-case__form">
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

        <fieldset disabled={uploading} className="create-case__files">
          <legend>{t("evidence.intake.dropzone")}</legend>
          <FileDropZone locale={locale} onFiles={addFiles} />
          {createdCaseId !== null ? (
            <p className="create-case__files-frozen">
              Case {createdCaseId} created. Additional files uploaded from here
              will be attached to it.
            </p>
          ) : null}
          {queued.length > 0 ? (
            <ul className="create-case__files-list">
              {queued.map((q, i) => (
                <li key={i} className={`file file--${q.status}`}>
                  <span className="file__name">{q.file.name}</span>
                  <span className="file__size">{q.file.size} bytes</span>
                  <span className="file__status">{q.status}</span>
                  {q.error ? (
                    <span className="file__error">{q.error}</span>
                  ) : null}
                  {q.status !== "uploading" ? (
                    <button
                      type="button"
                      className="btn btn--link"
                      onClick={() => removeFile(i)}
                    >
                      Remove
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
        </fieldset>

        <div className="create-case__actions">
          <button type="submit" className="btn btn--primary" disabled={busy}>
            {createdCaseId !== null
              ? "Continue to case"
              : busy
                ? pending > 0
                  ? `Uploading (${pending} left)…`
                  : t("case.create.action.create")
                : t("case.create.action.create")}
          </button>
          <a className="btn" href="#/cases">
            {t("case.create.action.cancel")}
          </a>
        </div>
      </form>
      </div>
      <div className="create-case__tree">
        <CaseTreePanel locale={locale} adapter={adapter} />
      </div>
    </section>
  );
}
