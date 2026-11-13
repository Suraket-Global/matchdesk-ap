import { useState, type ReactNode } from "react";
import { download, errorText } from "../api/client";

/** A download with its failure shown where it happened (B10, outside QA item 9): the reason and a
 * "Retry download" button next to the control, not a toast that looks like success. */
export function DownloadButton(props: { path: string; filename: string; className?: string; children: ReactNode; ariaLabel?: string }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const go = async () => {
    setBusy(true);
    setFailed(null);
    try {
      await download(props.path, props.filename);
    } catch (e) {
      setFailed(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="download-wrap">
      <button type="button" className={props.className ?? "btn"} aria-label={props.ariaLabel} disabled={busy} onClick={() => void go()}>
        {busy ? "Preparing the download…" : props.children}
      </button>
      {failed && (
        <span className="download-failed" role="alert">
          <span className="error-text small">Download failed: {failed}</span>
          <button type="button" className="btn small" onClick={() => void go()}>
            Retry download
          </button>
        </span>
      )}
    </span>
  );
}
