import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Download, Maximize2, Minimize2, MoveHorizontal, ZoomIn, ZoomOut } from "lucide-react";
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { documentBytes } from "../api/client";
import { DownloadButton } from "./DownloadButton";

// Supplier PDFs are drawn by PDF.js with script execution and dynamic code evaluation off
// (TRD 8.7): no eval, no XFA forms, no scripting; the bytes come only through the API.
GlobalWorkerOptions.workerSrc = workerUrl;

/** B15: the image type of a stored document from its first bytes (PNG or JPEG), or null for a PDF
 * or anything else. Read from the bytes, not the file name, as the server stores them. */
export function imageType(bytes: ArrayBuffer): "image/png" | "image/jpeg" | null {
  const b = new Uint8Array(bytes.slice(0, 8));
  if (b[0] === 0x89 && b[1] === 0x50 && b[2] === 0x4e && b[3] === 0x47) return "image/png";
  if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return "image/jpeg";
  return null;
}

export default function PdfViewer({ documentId, label, initialPage = 1 }: { documentId: string; label: string; initialPage?: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(initialPage);
  // B8: an expanded view over the whole window, for reading a dense invoice; Escape returns.
  const [expanded, setExpanded] = useState(false);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!wrap.current || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((e) => setWidth(Math.round(e[0].contentRect.width)));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setExpanded(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);
  const [zoom, setZoom] = useState<number | null>(null); // null: fit the pane width
  const [shown, setShown] = useState(1);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  // B15: a PNG or JPEG invoice is shown as an image from the same authenticated bytes (a blob URL,
  // allowed by the img-src policy); PDF.js draws only PDFs.
  const [image, setImage] = useState<{ url: string; width: number; ext: string } | null>(null);
  useEffect(() => {
    let cancelled = false;
    let doc: PDFDocumentProxy | null = null;
    let url: string | null = null;
    setError(false);
    setImage(null);
    documentBytes(documentId)
      .then((bytes) => {
        const type = imageType(bytes);
        if (type) {
          url = URL.createObjectURL(new Blob([bytes], { type }));
          if (!cancelled) setImage({ url, width: 0, ext: type === "image/png" ? "png" : "jpg" });
          return null;
        }
        return getDocument({ data: new Uint8Array(bytes), isEvalSupported: false, enableXfa: false, disableAutoFetch: true }).promise;
      })
      .then((d) => {
        if (!d) return;
        doc = d;
        if (!cancelled) {
          setPdf(d);
          setPage(Math.min(Math.max(1, initialPage), d.numPages));
        }
      })
      .catch(() => !cancelled && setError(true));
    return () => {
      cancelled = true;
      void doc?.destroy();
      if (url) URL.revokeObjectURL(url);
    };
  }, [documentId, attempt]); // eslint-disable-line react-hooks/exhaustive-deps -- the first page is read once per document
  useEffect(() => {
    if (!pdf || !canvas.current) return;
    let task: { cancel: () => void } | null = null;
    let cancelled = false;
    pdf.getPage(page).then((p) => {
      // A page or zoom change before the page arrived: draw nothing for the old one (review, minor).
      if (cancelled || !canvas.current) return;
      const base = p.getViewport({ scale: 1 }).width;
      const fit = wrap.current ? Math.max(0.5, Math.min(2, (wrap.current.clientWidth - 26) / base)) : 1;
      const z = zoom ?? fit;
      setShown(z);
      const viewport = p.getViewport({ scale: z * (window.devicePixelRatio || 1) });
      const c = canvas.current!;
      c.width = viewport.width;
      c.height = viewport.height;
      c.style.width = `${viewport.width / (window.devicePixelRatio || 1)}px`;
      const ctx = c.getContext("2d");
      if (!ctx) return;
      const r = p.render({ canvasContext: ctx, viewport });
      task = r;
      r.promise.catch(() => undefined);
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [pdf, page, zoom, width, expanded]);
  if (error)
    return (
      <div className="banner warn" role="alert">
        <p>The document could not be shown. The values read from it are listed beside it.</p>
        <button className="btn small" onClick={() => setAttempt((a) => a + 1)}>
          Retry loading document
        </button>
      </div>
    );
  if (image) {
    // Fit: the pane width (never larger than the image itself); zoom: a share of the image's width.
    const natural = image.width;
    const room = (wrap.current?.clientWidth ?? 0) - 26;
    const fitScale = natural && room > 0 ? Math.max(0.1, Math.min(1, room / natural)) : 1;
    const z = zoom ?? fitScale;
    return (
      <div className={`pdf ${expanded ? "expanded" : ""}`} role={expanded ? "dialog" : undefined} aria-modal={expanded || undefined} aria-label={expanded ? `${label}, expanded` : undefined}>
        <div className="pdf-toolbar">
          <span className="small">Image</span>
          <span className="grow" style={{ flex: 1 }} />
          <button className="btn small icon-btn sm" onClick={() => setZoom(Math.max(0.25, z - 0.25))} aria-label="Zoom out">
            <ZoomOut size={16} aria-hidden="true" />
          </button>
          <span className="small num" aria-live="polite">{Math.round(z * 100)}%</span>
          <button className="btn small icon-btn sm" onClick={() => setZoom(Math.min(3, z + 0.25))} aria-label="Zoom in">
            <ZoomIn size={16} aria-hidden="true" />
          </button>
          <button className="btn small ghost" aria-pressed={zoom === null} onClick={() => setZoom(null)}>
            <MoveHorizontal size={14} aria-hidden="true" />
            Fit width
          </button>
          <button className="btn small icon-btn sm" onClick={() => setExpanded((x) => !x)} aria-label={expanded ? "Close the expanded view" : "Expand the document"}>
            {expanded ? <Minimize2 size={16} aria-hidden="true" /> : <Maximize2 size={16} aria-hidden="true" />}
          </button>
          <DownloadButton className="btn small icon-btn sm" path={`/api/v1/documents/${documentId}/content`} filename={`document.${image.ext}`} ariaLabel="Download original">
            <Download size={16} aria-hidden="true" />
          </DownloadButton>
        </div>
        <div className="pdf-canvas-wrap" ref={wrap} tabIndex={0} aria-label={label}>
          <img
            className="doc-image"
            src={image.url}
            alt={`${label}. The values read from it are listed as text beside it.`}
            style={natural ? { width: `${Math.round(natural * z)}px` } : { maxWidth: "100%" }}
            onLoad={(e) => {
              // Read the width now: the event's target is gone by the time the updater runs.
              const w = e.currentTarget.naturalWidth;
              setImage((i) => (i ? { ...i, width: w } : i));
            }}
            onError={() => setError(true)}
          />
        </div>
      </div>
    );
  }
  return (
    <div className={`pdf ${expanded ? "expanded" : ""}`} role={expanded ? "dialog" : undefined} aria-modal={expanded || undefined} aria-label={expanded ? `${label}, expanded` : undefined}>
      <div className="pdf-toolbar">
        <button className="btn small icon-btn sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} aria-label="Previous page">
          <ChevronLeft size={16} aria-hidden="true" />
        </button>
        <span aria-live="polite" className="small">
          Page {page} of {pdf?.numPages ?? "…"}
        </span>
        <button className="btn small icon-btn sm" disabled={!pdf || page >= pdf.numPages} onClick={() => setPage((p) => p + 1)} aria-label="Next page">
          <ChevronRight size={16} aria-hidden="true" />
        </button>
        <span className="grow" style={{ flex: 1 }} />
        <button className="btn small icon-btn sm" onClick={() => setZoom(Math.max(0.5, shown - 0.25))} aria-label="Zoom out">
          <ZoomOut size={16} aria-hidden="true" />
        </button>
        <span className="small num" aria-live="polite">{Math.round(shown * 100)}%</span>
        <button className="btn small icon-btn sm" onClick={() => setZoom(Math.min(3, shown + 0.25))} aria-label="Zoom in">
          <ZoomIn size={16} aria-hidden="true" />
        </button>
        <button className="btn small ghost" aria-pressed={zoom === null} onClick={() => setZoom(null)}>
          <MoveHorizontal size={14} aria-hidden="true" />
          Fit width
        </button>
        <button className="btn small icon-btn sm" onClick={() => setExpanded((x) => !x)} aria-label={expanded ? "Close the expanded view" : "Expand the document"}>
          {expanded ? <Minimize2 size={16} aria-hidden="true" /> : <Maximize2 size={16} aria-hidden="true" />}
        </button>
        <DownloadButton className="btn small icon-btn sm" path={`/api/v1/documents/${documentId}/content`} filename="document.pdf" ariaLabel="Download original">
          <Download size={16} aria-hidden="true" />
        </DownloadButton>
      </div>
      <div className="pdf-canvas-wrap" ref={wrap} tabIndex={0} aria-label={`${label}, page ${page}`}>
        <canvas ref={canvas} role="img" aria-label={`${label}, page ${page}. The values read from it are listed as text beside it.`} />
      </div>
    </div>
  );
}
