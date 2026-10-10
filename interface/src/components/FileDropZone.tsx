import { useRef } from "react";
import { translate } from "../i18n";
import type { Locale } from "../types";

interface Props {
  locale: Locale;
  onFiles: (files: File[]) => void;
}

export function FileDropZone({ locale, onFiles }: Props) {
  const filesRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);
  const take = (list: FileList | null) => {
    if (list && list.length > 0) onFiles(Array.from(list));
  };
  return (
    <div
      className="dropzone"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        take(e.dataTransfer.files);
      }}
    >
      <p>{translate(locale, "evidence.intake.dropzone")}</p>
      <button type="button" onClick={() => filesRef.current?.click()}>
        {translate(locale, "evidence.intake.choose_files")}
      </button>
      <button type="button" onClick={() => folderRef.current?.click()}>
        {translate(locale, "evidence.intake.choose_folder")}
      </button>
      <input
        ref={filesRef}
        data-testid="file-input"
        type="file"
        multiple
        hidden
        onChange={(e) => take(e.target.files)}
      />
      <input
        ref={folderRef}
        type="file"
        hidden
        {...({ webkitdirectory: "" } as Record<string, string>)}
        onChange={(e) => take(e.target.files)}
      />
    </div>
  );
}
