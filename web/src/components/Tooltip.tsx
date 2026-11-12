import { cloneElement, isValidElement, useId, useState, type ReactElement, type ReactNode } from "react";

/** Shows a short text on hover and keyboard focus; the trigger is described by it (WCAG 1.4.13). */
export function Tooltip({ text, children }: { text: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const child = isValidElement(children)
    ? cloneElement(children as ReactElement<Record<string, unknown>>, { "aria-describedby": open ? id : undefined })
    : children;
  return (
    <span
      className="tip"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
    >
      {child}
      {open && (
        <span role="tooltip" id={id} className="tip-bubble">
          {text}
        </span>
      )}
    </span>
  );
}
