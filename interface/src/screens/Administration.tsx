import { useEffect, useState, type FormEvent } from "react";
import type {
  AdminMember,
  CaseRow,
  InviteMemberInput,
  createAdapter,
} from "../adapter";
import { DataTable, type Column } from "../components/DataTable";
import { FormField } from "../components/FormField";
import { ConfirmWithReasonDialog } from "../components/ConfirmWithReasonDialog";
import { StateBlock } from "../components/StateBlock";
import { translate } from "../i18n";
import type { Locale, SessionRole } from "../types";

type Props = {
  locale: Locale;
  adapter: ReturnType<typeof createAdapter>;
};
type Load =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; members: readonly AdminMember[]; cases: readonly CaseRow[] };

export function Administration({ locale, adapter }: Props) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [email, setEmail] = useState("");
  const [credential, setCredential] = useState("");
  const [role, setRole] = useState<SessionRole>("reviewer");
  const [caseIds, setCaseIds] = useState<string[]>([]);
  const [formError, setFormError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [pendingRole, setPendingRole] = useState<{
    member: AdminMember;
    role: SessionRole;
  } | null>(null);
  const t = (
    key: string,
    parameters?: Record<string, string | number>,
  ) => translate(locale, key as never, parameters as never);

  useEffect(() => {
    let active = true;
    Promise.all([adapter.members.list(), adapter.cases.list()]).then(
      ([memberResult, caseResult]) => {
        if (!active) return;
        if (!memberResult.ok || !caseResult.ok) {
          const error = !memberResult.ok
            ? memberResult.error
            : !caseResult.ok
              ? caseResult.error
              : "BACKEND_UNREACHABLE";
          setLoad({ kind: "error", message: t(`error.${error.toLowerCase()}`) });
          return;
        }
        setLoad({
          kind: "ready",
          members: memberResult.value,
          cases: caseResult.value,
        });
      },
    );
    return () => {
      active = false;
    };
  }, [adapter, locale]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (load.kind !== "ready" || submitting) return;
    setFormError("");
    setSuccessMessage("");
    if (!event.currentTarget.checkValidity()) {
      setFormError(t("error.invalid_form"));
      return;
    }
    setSubmitting(true);
    const input: InviteMemberInput = {
      email: email.trim(),
      role,
      caseIds,
      credential: credential.trim() || undefined,
    };
    const result = await adapter.members.invite(input);
    setSubmitting(false);
    if (!result.ok) {
      setFormError(t(`error.${result.error.toLowerCase()}`));
      return;
    }
    setLoad({ ...load, members: [...load.members, result.value] });
    setEmail("");
    setCredential("");
    setCaseIds([]);
    setSuccessMessage(t("administration.invite.success"));
  }

  async function confirmRoleChange(reason: string) {
    if (load.kind !== "ready" || !pendingRole) return;
    const result = await adapter.members.changeRole(
      pendingRole.member.id,
      pendingRole.role,
      reason,
    );
    if (!result.ok) {
      setFormError(t(`error.${result.error.toLowerCase()}`));
      setPendingRole(null);
      return;
    }
    setLoad({
      ...load,
      members: load.members.map((member) =>
        member.id === result.value.id ? result.value : member,
      ),
    });
    setPendingRole(null);
    setSuccessMessage(t("administration.role_change.success"));
  }

  if (load.kind === "loading") {
    return <StateBlock locale={locale} kind="loading" />;
  }
  if (load.kind === "error") {
    return (
      <StateBlock
        locale={locale}
        kind="error"
        message={load.message}
      />
    );
  }

  const columns: Column<AdminMember>[] = [
    { id: "name", header: t("administration.members.column.name"), render: (member) => member.name },
    { id: "email", header: t("administration.members.column.email"), render: (member) => member.email },
    {
      id: "role",
      header: t("administration.members.column.role"),
      render: (member) => (
        <label>
          <span className="visually-hidden">{member.name}</span>
          <select
            aria-label={t("administration.role_change.action", { name: member.name })}
            value={member.role}
            onChange={(event) =>
              setPendingRole({ member, role: event.target.value as SessionRole })
            }
          >
            <option value="case_admin">{t("member.role.case_admin")}</option>
            <option value="reviewer">{t("member.role.reviewer")}</option>
            <option value="auditor">{t("member.role.auditor")}</option>
          </select>
        </label>
      ),
    },
    { id: "status", header: t("administration.members.column.status"), render: (member) => t(`member.status.${member.status}`) },
    {
      id: "credential",
      header: t("administration.members.column.credential"),
      render: (member) => {
        const fp = member.credentialFingerprint;
        if (!fp) return t("administration.members.credential.none");
        if (fp === "pending") return t("administration.members.credential.pending");
        return fp.slice(0, 8) + "…";
      },
    },
    {
      id: "cases",
      header: t("administration.members.column.cases"),
      render: (member) =>
        member.caseIds
          .map((id) => {
            const assignedCase = load.cases.find((item) => item.id === id);
            return assignedCase ? assignedCase.key : id;
          })
          .join(", "),
    },
  ];

  return (
    <section className="administration" aria-labelledby="administration-title">
      <h1 id="administration-title">{t("administration.title")}</h1>
      <section aria-labelledby="administration-members-title">
        <h2 id="administration-members-title">
          {t("administration.members.title")}
        </h2>
        <DataTable
          caption={t("administration.members.title")}
          columns={columns}
          rows={load.members}
          rowKey={(member) => member.id}
        />
      </section>
      <section aria-labelledby="administration-invite-title">
        <h2 id="administration-invite-title">
          {t("administration.invite.title")}
        </h2>
        <form
          aria-label={t("administration.invite.title")}
          onSubmit={submit}
          noValidate
        >
          <label className="form-field" htmlFor="member-email">
            {t("administration.invite.email")}
            <input
              id="member-email"
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label className="form-field" htmlFor="member-credential">
            {t("administration.invite.credential")}
            <input
              id="member-credential"
              type="text"
              value={credential}
              onChange={(event) => setCredential(event.target.value)}
              aria-describedby="member-credential-help"
            />
            <p id="member-credential-help" className="form-field__help">
              {t("administration.invite.credential_help")}
            </p>
          </label>
          <FormField
            id="member-role"
            label={t("administration.invite.role")}
            value={role}
            type="select"
            onChange={(value) => setRole(value as SessionRole)}
            options={[
              { value: "case_admin", label: t("member.role.case_admin") },
              { value: "reviewer", label: t("member.role.reviewer") },
              { value: "auditor", label: t("member.role.auditor") },
            ]}
            required
          />
          <fieldset className="administration__assignments">
            <legend>{t("administration.invite.cases")}</legend>
            {load.cases.map((assignedCase) => (
              <label key={assignedCase.id}>
                <input
                  type="checkbox"
                  value={assignedCase.id}
                  checked={caseIds.includes(assignedCase.id)}
                  onChange={(event) =>
                    setCaseIds((current) =>
                      event.target.checked
                        ? [...current, assignedCase.id]
                        : current.filter((id) => id !== assignedCase.id),
                    )
                  }
                />
                {assignedCase.key} · {assignedCase.title}
              </label>
            ))}
          </fieldset>
          {successMessage ? <p role="status">{successMessage}</p> : null}
          <button type="submit" className="btn btn--primary" disabled={submitting}>
            {t("administration.invite.action")}
          </button>
        </form>
      </section>
      {formError ? <p role="alert">{formError}</p> : null}
      <ConfirmWithReasonDialog
        locale={locale}
        open={pendingRole !== null}
        title={t("administration.confirm.title")}
        reasonLabel={t("administration.confirm.reason")}
        confirmLabel={t("administration.confirm.action")}
        cancelLabel={t("administration.confirm.cancel")}
        onConfirm={confirmRoleChange}
        onCancel={() => setPendingRole(null)}
      />
    </section>
  );
}
