import { useState } from "react";
import { translate, type MessageKey } from "../i18n";
import type { createAdapter, EvidenceAnalysis, ExtractStatus } from "../adapter";
import type { Locale } from "../types";
import { FileDropZone } from "../components/FileDropZone";
import { ProgressStrip, type IntakeState } from "../components/ProgressStrip";

/**
 * The upload's outcome mapped onto the progress strip's states.
 *
 * This used to read `processingStatus === "stored" ? "stored" : "done"`, which
 * rendered every other value as a success: an artifact the connector refused to
 * read, one above the size ceiling, and one whose analysis threw all appeared as
 * "Done". The mapping is now exhaustive over the vocabulary the API sends, and
 * anything unrecognised lands on `failed` rather than on `done`, because an
 * unknown status is not evidence that the artifact was read.
 */
const INTAKE_STATE: Record<ExtractStatus, IntakeState> = {
  stored: "stored",
  extracted: "done",
  unsupported: "failed",
  empty: "failed",
  skipped_oversize: "failed",
  failed: "failed",
};

/**
 * The stage a failed read is attributed to. Extraction is the "Scanned" step of
 * the strip; the earlier steps did succeed, and saying so keeps the strip honest
 * about how far the artifact actually got.
 */
const READ_STAGE = "scanned";

const NOT_READ_KEY: Partial<Record<ExtractStatus, string>> = {
  unsupported: "evidence.intake.result.unsupported",
  empty: "evidence.intake.result.empty",
  skipped_oversize: "evidence.intake.result.skipped_oversize",
  failed: "evidence.intake.result.failed",
};

/**
 * The category and source vocabularies the API accepts, mirroring
 * `ALLOWED_CATEGORIES` / `ALLOWED_SOURCES` in interface/anchorum_api.py.
 *
 * Duplicated rather than fetched so the selects can render before any request
 * is made. The server stays the authority: a value outside its allowlist is
 * rejected with 422 INVALID_CATEGORY / INVALID_SOURCE, so the two lists drifting
 * apart produces a refusal, not a silently stored unrecognised value.
 */
const CATEGORIES = ["medical", "payroll", "correspondence", "pleading", "other"] as const;
const SOURCES = ["clinic", "insurer", "employer", "court", "other"] as const;

function intakeStateFor(status: ExtractStatus | undefined): IntakeState {
  // No status at all means the bytes were accepted and nothing further was
  // reported, which is exactly what "stored" says.
  return status ? INTAKE_STATE[status] ?? "failed" : "stored";
}

interface Row {
  key: number;
  name: string;
  size: number;
  type: string;
  state: IntakeState;
  failedStage?: "received" | "preserved" | "scanned" | "indexed";
  error?: string;
  /** Present when the artifact was not read, so the row can say why. */
  notReadKey?: string;
  analysis?: EvidenceAnalysis | null;
  duplicate: boolean;
  id?: string;
  hash?: string;
}

interface Props {
  locale: Locale;
  adapter: ReturnType<typeof createAdapter>;
  caseId: string;
}

let nextKey = 0;

export function EvidenceIntake({ locale, adapter, caseId }: Props) {
  const [rows, setRows] = useState<Row[]>([]);
  // One selection per batch: a batch of files normally arrives from one source,
  // and per-row selection would need the same two fields on `Row`.
  const [category, setCategory] = useState("");
  const [source, setSource] = useState("");

  const patch = (key: number, change: Partial<Row>) =>
    setRows((all) => all.map((r) => (r.key === key ? { ...r, ...change } : r)));

  const onFiles = (files: File[]) => {
    const fresh = files.map<Row>((f) => ({
      key: nextKey++,
      name: f.name,
      size: f.size,
      type: f.type || "",
      state: "pending",
      duplicate: false,
    }));
    setRows((all) => [...all, ...fresh]);
    fresh.forEach((row, i) => {
      void (async () => {
        patch(row.key, { state: "active" });
        try {
          const result = await adapter.evidence.ingest(caseId, {
            name: files[i].name,
            size: files[i].size,
            type: files[i].type,
            bytes: await files[i].arrayBuffer(),
            category: category || null,
            source: source || null,
          });
          if (result.ok) {
            const state = intakeStateFor(result.value.processingStatus);
            patch(row.key, {
              state,
              // Only a read failure is attributed to a stage. A stored artifact
              // did not fail; it simply was not read, and the state says that.
              failedStage:
                state === "failed" ? READ_STAGE : undefined,
              notReadKey: result.value.processingStatus
                ? NOT_READ_KEY[result.value.processingStatus]
                : undefined,
              analysis: result.value.analysis ?? null,
              id: result.value.id,
              hash: result.value.hash,
              duplicate: result.value.duplicate,
            });
          } else {
            patch(row.key, {
              state: "failed",
              failedStage: result.failedStage,
              error: result.error,
            });
          }
        } catch {
          patch(row.key, { state: "failed", error: "BACKEND_UNREACHABLE" });
        }
      })();
    });
  };

  return (
    <section className="evidence-intake">
      <h1>{translate(locale, "evidence.intake.title")}</h1>
      <nav aria-label={translate(locale, "nav.evidence_actions")}>
        <a href={`#/cases/${encodeURIComponent(caseId)}/register`}>
          {translate(locale, "evidence.register.title")}
        </a>
        {" · "}
        <a href="#/cases">{translate(locale, "case.list.browse")}</a>
      </nav>
      <p>
        {translate(locale, "evidence.intake.retention_policy", {
          policy: translate(locale, "evidence.intake.policy_default"),
        })}
      </p>
      <label>
        {translate(locale, "evidence.intake.category")}
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">{translate(locale, "evidence.intake.unset")}</option>
          {CATEGORIES.map((value) => (
            <option key={value} value={value}>
              {translate(locale, `evidence.category.${value}` as MessageKey)}
            </option>
          ))}
        </select>
      </label>
      <label>
        {translate(locale, "evidence.intake.source")}
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">{translate(locale, "evidence.intake.unset")}</option>
          {SOURCES.map((value) => (
            <option key={value} value={value}>
              {translate(locale, `evidence.source.${value}` as MessageKey)}
            </option>
          ))}
        </select>
      </label>
      <FileDropZone locale={locale} onFiles={onFiles} />
      {rows.length > 0 ? (
        <table>
          <thead>
            <tr>
              {(["file", "size", "type", "duplicate", "progress", "result"] as const).map((c) => (
                <th key={c}>{translate(locale, `evidence.intake.column.${c}` as MessageKey)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td>{r.name}</td>
                <td>{r.size}</td>
                <td>{r.type}</td>
                <td>{r.duplicate ? translate(locale, "evidence.intake.duplicate_candidate") : ""}</td>
                <td>
                  <ProgressStrip
                    locale={locale}
                    state={r.state}
                    failedStage={r.state === "failed" ? r.failedStage : undefined}
                  />
                  {r.notReadKey ? (
                    <p role="alert">{translate(locale, r.notReadKey as MessageKey)}</p>
                  ) : null}
                  {r.analysis?.warning ? (
                    <p>
                      {translate(locale, "evidence.intake.coverage_warning", {
                        warning: r.analysis.warning,
                      })}
                    </p>
                  ) : null}
                  {r.error ? (
                    <p role="alert">
                      {translate(
                        locale,
                        r.error === "FEATURE_UNAVAILABLE"
                          ? "error.feature_unavailable"
                          : r.error === "NOT_FOUND"
                            ? "error.not_found"
                            : "error.backend_unreachable",
                      )}
                    </p>
                  ) : null}
                </td>
                <td>
                  {r.id && r.hash ? (
                    <>
                      <span>
                        {translate(locale, "evidence.intake.completed", { id: r.id, hash: r.hash })}
                      </span>{" "}
                      <a href={`#/cases/${encodeURIComponent(caseId)}/register`}>
                        {translate(locale, "evidence.intake.open")}
                      </a>{" "}
                      <button type="button" onClick={() => void navigator.clipboard?.writeText(r.hash!)}>
                        {translate(locale, "evidence.intake.copy_hash")}
                      </button>
                    </>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
