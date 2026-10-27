import { useRef } from "react";
import { translate } from "../i18n";
import type { Locale } from "../types";

interface Props {
  locale: Locale;
  onFiles: (files: File[]) => void;
  /**
   * A MIME/extension filter for the file picker, e.g. ".eml". It is a hint for
   * the picker only: the control still accepts a dropped file of any type,
   * because a browser that ignores `accept` must not be the reason a legitimate
   * message cannot be submitted. The screen decides what it can process.
   */
  accept?: string;
}

export function FileDropZone({ locale, onFiles, accept }: Props) {
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
        accept={accept}
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
