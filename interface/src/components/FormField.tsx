import type { ReactNode } from "react";

export interface FormFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "textarea" | "select";
  options?: readonly { value: string; label: string }[];
  help?: string;
  error?: string;
  required?: boolean;
}

export function FormField({
  id,
  label,
  value,
  onChange,
  type = "text",
  options = [],
  help,
  error,
  required,
}: FormFieldProps) {
  const describedBy =
    [help ? `${id}-help` : "", error ? `${id}-error` : ""]
      .filter(Boolean)
      .join(" ") || undefined;
  const common = {
    id,
    value,
    required,
    "aria-invalid": error ? true : undefined,
    "aria-describedby": describedBy,
  };
  let control: ReactNode;
  if (type === "select") {
    control = (
      <select {...common} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    );
  } else if (type === "textarea") {
    control = (
      <textarea {...common} rows={4} onChange={(e) => onChange(e.target.value)} />
    );
  } else {
    control = (
      <input {...common} type="text" onChange={(e) => onChange(e.target.value)} />
    );
  }
  return (
    <div className={error ? "form-field form-field--error" : "form-field"}>
      <label htmlFor={id}>{label}</label>
      {control}
      {help ? (
        <p id={`${id}-help`} className="form-field__help">
          {help}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} className="form-field__error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
