import { useEffect, useRef, useState, type FormEvent } from "react";
import { translate } from "../i18n";
import type { Locale } from "../types";

interface ConfirmWithReasonDialogProps {
  locale: Locale;
  open: boolean;
  title: string;
  reasonLabel: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: (reason: string) => Promise<void>;
  onCancel: () => void;
}

export function ConfirmWithReasonDialog({
  locale,
  open,
  title,
  reasonLabel,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
}: ConfirmWithReasonDialogProps) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const t = (key: string) => translate(locale, key as never);

  useEffect(() => {
    if (!open) return;
    setReason("");
    setError("");
    reasonRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = document.querySelector<HTMLElement>(
        '[role="dialog"][aria-modal="true"]',
      );
      const controls = dialog?.querySelectorAll<HTMLElement>(
        "textarea, button:not(:disabled)",
      );
      if (!controls?.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [busy, onCancel, open]);

  if (!open) return null;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = reason.trim();
    if (!value) {
      setError(t("administration.confirm.reason_required"));
      reasonRef.current?.focus();
      return;
    }
    setBusy(true);
    try {
      await onConfirm(value);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="confirm-dialog__backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel();
      }}
    >
      <section
        className="confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
      >
        <h2 id="confirm-dialog-title">{title}</h2>
        <form onSubmit={submit} noValidate>
          <label htmlFor="confirm-dialog-reason">{reasonLabel}</label>
          <textarea
            id="confirm-dialog-reason"
            ref={reasonRef}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            required
            aria-invalid={Boolean(error)}
            aria-describedby={error ? "confirm-dialog-error" : undefined}
          />
          {error ? (
            <p id="confirm-dialog-error" role="alert">
              {error}
            </p>
          ) : null}
          <div className="confirm-dialog__actions">
            <button type="button" className="btn" onClick={onCancel} disabled={busy}>
              {cancelLabel}
            </button>
            <button
              type="submit"
              className="btn btn--primary"
              disabled={busy}
            >
              {confirmLabel}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
