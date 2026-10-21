import { useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { translate } from "../i18n";
import type { Locale } from "../types";

// pdfjs loads its worker from a URL. Vite rewrites the `?url` import into the
// emitted asset path, which is why `optimizeDeps.exclude` for `pdfjs-dist` sits
// in vite.config.ts: without it the pre-bundled copy wins and the worker 404s.
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const MIN_SCALE = 0.6;
const MAX_SCALE = 3;
const SCALE_STEP = 0.2;

type Props = {
  locale: Locale;
  fileUrl: string;
};

/**
 * Renders one page of a PDF served by `GET /evidence/{id}/download`.
 *
 * Single-page navigation rather than continuous scroll: an evidence bundle can
 * run to hundreds of pages, and rendering them all through canvas will exhaust
 * memory long before the reader reaches the page they care about.
 */
export function PdfViewer({ locale, fileUrl }: Props) {
  const [pageCount, setPageCount] = useState(0);
  const [page, setPage] = useState(1);
  const [scale, setScale] = useState(1.2);
  const [failed, setFailed] = useState(false);

  const t = (k: string, parameters?: Record<string, string | number>) =>
    translate(locale, k as never, parameters);

  const hasPages = pageCount > 0;
  const atFirst = page <= 1;
  const atLast = !hasPages || page >= pageCount;

  if (failed) {
    return (
      <section className="pdf-viewer" aria-label={t("pdf.title")}>
        <p role="alert" className="form-error">
          {t("pdf.error")}
        </p>
        <a href={fileUrl}>{t("evidence.viewer.download_original")}</a>
      </section>
    );
  }

  return (
    <section className="pdf-viewer" aria-label={t("pdf.title")}>
      <div className="pdf-toolbar">
        <button
          type="button"
          className="btn"
          onClick={() => setPage((n) => Math.max(1, n - 1))}
          disabled={atFirst}
          aria-label={t("pdf.prev")}
        >
          ‹
        </button>
        <span className="pdf-counter">
          {hasPages ? t("pdf.page_of", { page, pages: pageCount }) : t("pdf.loading")}
        </span>
        <button
          type="button"
          className="btn"
          onClick={() => setPage((n) => Math.min(pageCount, n + 1))}
          disabled={atLast}
          aria-label={t("pdf.next")}
        >
          ›
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => setScale((s) => Math.max(MIN_SCALE, s - SCALE_STEP))}
          aria-label={t("pdf.zoom_out")}
        >
          −
        </button>
        <span className="pdf-counter">{Math.round(scale * 100)}%</span>
        <button
          type="button"
          className="btn"
          onClick={() => setScale((s) => Math.min(MAX_SCALE, s + SCALE_STEP))}
          aria-label={t("pdf.zoom_in")}
        >
          +
        </button>
        <a className="pdf-download" href={fileUrl}>
          {t("evidence.viewer.download_original")}
        </a>
      </div>
      <div className="pdf-canvas">
        <Document
          file={fileUrl}
          onLoadSuccess={(pdf) => setPageCount(pdf.numPages)}
          onLoadError={() => setFailed(true)}
          loading={<p className="pdf-loading">{t("pdf.loading")}</p>}
        >
          <Page
            pageNumber={page}
            scale={scale}
            renderAnnotationLayer={false}
            renderTextLayer
          />
        </Document>
      </div>
    </section>
  );
}
