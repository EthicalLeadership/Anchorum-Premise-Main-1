import { useState } from "react";
import { translate } from "../i18n";
import type { createAdapter } from "../adapter";
import type { Locale } from "../types";
import { FileDropZone } from "../components/FileDropZone";
import { ProgressStrip, type IntakeState } from "../components/ProgressStrip";

interface Row {
  key: number;
  name: string;
  size: number;
  type: string;
  state: IntakeState;
  failedStage?: "received" | "preserved" | "scanned" | "indexed";
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

  const patch = (key: number, change: Partial<Row>) =>
    setRows((all) => all.map((r) => (r.key === key ? { ...r, ...change } : r)));

  const onFiles = (files: File[]) => {
    const fresh = files.map<Row>((f) => ({
      key: nextKey++,
      name: f.name,
      size: f.size,
      type: f.type || "—",
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
          });
          if (result.ok) {
            patch(row.key, {
              state: "done",
              id: result.value.id,
              hash: result.value.hash,
              duplicate: result.value.duplicate,
            });
          } else {
            patch(row.key, {
              state: "failed",
              failedStage: result.failedStage,
            });
          }
        } catch {
          patch(row.key, { state: "failed" });
        }
      })();
    });
  };

  return (
    <section className="evidence-intake">
      <h1>{translate(locale, "evidence.intake.title")}</h1>
      <p>
        {translate(locale, "evidence.intake.retention_policy", {
          policy: translate(locale, "evidence.intake.policy_default"),
        })}
      </p>
      <FileDropZone locale={locale} onFiles={onFiles} />
      {rows.length > 0 ? (
        <table>
          <thead>
            <tr>
              {(["file", "size", "type", "duplicate", "progress", "result"] as const).map((c) => (
                <th key={c}>{translate(locale, `evidence.intake.column.${c}` as never)}</th>
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
