import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

/** Label, control, hint and error wired together; the control gets the ids through the render prop. */
export function Field(props: {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  className?: string;
  children: (ids: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode;
}) {
  const id = useId();
  const hintId = props.hint ? `${id}-hint` : undefined;
  const errId = props.error ? `${id}-err` : undefined;
  return (
    <div className={`field ${props.className ?? ""}`}>
      <label htmlFor={id}>{props.label}</label>
      {props.children({ id, describedBy: [hintId, errId].filter(Boolean).join(" ") || undefined, invalid: !!props.error })}
      {props.hint && (
        <span className="hint" id={hintId}>
          {props.hint}
        </span>
      )}
      {props.error && (
        <span className="error" id={errId}>
          {props.error}
        </span>
      )}
    </div>
  );
}

type InputProps = InputHTMLAttributes<HTMLInputElement> & { label: ReactNode; hint?: ReactNode; error?: string | null; icon?: ReactNode };

/** A labelled text input. */
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ label, hint, error, icon, className, ...rest }, ref) {
  return (
    <Field label={label} hint={hint} error={error} className={className}>
      {({ id, describedBy, invalid }) =>
        icon ? (
          <span className="input-wrap">
            {icon}
            <input ref={ref} id={id} aria-describedby={describedBy} aria-invalid={invalid || undefined} {...rest} />
          </span>
        ) : (
          <input ref={ref} id={id} aria-describedby={describedBy} aria-invalid={invalid || undefined} {...rest} />
        )
      }
    </Field>
  );
});

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  options: readonly (readonly [string, string])[];
};

/** A labelled native select (native for keyboard and screen-reader behaviour). */
export function Select({ label, hint, error, options, className, ...rest }: SelectProps) {
  return (
    <Field label={label} hint={hint} error={error} className={className}>
      {({ id, describedBy, invalid }) => (
        <select id={id} aria-describedby={describedBy} aria-invalid={invalid || undefined} {...rest}>
          {options.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}

/** A checkbox with its label to the right. */
export function Checkbox({ label, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }) {
  return (
    <label className="check">
      <input type="checkbox" {...rest} />
      <span>{label}</span>
    </label>
  );
}
