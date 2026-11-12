import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

/** Focus goes back to the control that opened the dialog; if that control is gone (the row it was
 * on was resolved), to the page title. Also when the dialog unmounts instead of closing, which is how
 * most screens close it (B6 review minor: focus was lost after dialogs). */
function restoreFocus(opener: Element | null) {
  window.setTimeout(() => {
    if (opener instanceof HTMLElement && document.contains(opener)) opener.focus();
    else document.querySelector<HTMLElement>("main h1")?.focus();
  }, 0);
}

function useModal(open: boolean) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      opener.current = document.activeElement;
      d.showModal();
      // Focus starts on the safe button: the first one marked data-safe, else the first footer button.
      const safe = d.querySelector<HTMLElement>("[data-safe]") ?? d.querySelector<HTMLElement>(".modal-foot button");
      safe?.focus();
    } else if (!open && d.open) {
      d.close();
      restoreFocus(opener.current);
      opener.current = null;
    }
  }, [open]);
  useEffect(
    () => () => {
      if (opener.current) restoreFocus(opener.current);
    },
    [],
  );
  return ref;
}

interface OverlayProps {
  open: boolean;
  title: string;
  description?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer: ReactNode;
}

/** A modal dialog on the native <dialog>: focus trapped, Escape closes, focus returns to the opener. */
export function Dialog(props: OverlayProps) {
  const ref = useModal(props.open);
  const titleId = useId();
  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault();
        props.onClose();
      }}
    >
      <div className="modal-head">
        <div>
          <h2 id={titleId}>{props.title}</h2>
          {props.description && <p className="muted" style={{ margin: "4px 0 0" }}>{props.description}</p>}
        </div>
      </div>
      <div className="modal-body">{props.children}</div>
      <div className="modal-foot">{props.footer}</div>
    </dialog>
  );
}

/** A panel that slides in from the right, for detail that should not leave the current list. */
export function Drawer(props: OverlayProps) {
  const ref = useModal(props.open);
  const titleId = useId();
  return (
    <dialog
      ref={ref}
      className="drawer"
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault();
        props.onClose();
      }}
    >
      <div className="modal-head">
        <h2 id={titleId}>{props.title}</h2>
        <button className="btn ghost icon-btn sm" aria-label="Close" onClick={props.onClose}>
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <div className="modal-body">{props.children}</div>
      <div className="modal-foot">{props.footer}</div>
    </dialog>
  );
}
