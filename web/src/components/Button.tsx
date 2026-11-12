import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { Tooltip } from "./Tooltip";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "link";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  iconRight?: ReactNode;
  loading?: boolean;
  block?: boolean;
  /** Why the button is disabled; shown as its description so the reason is never hidden. */
  disabledReason?: string | null;
}

export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md", extra = ""): string {
  return ["btn", variant !== "secondary" && variant, size !== "md" && size, extra].filter(Boolean).join(" ");
}

/** The one button. Variants: primary (one per view), secondary, ghost, danger, link. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", icon, iconRight, loading, block, disabledReason, className, children, disabled, type, ...rest },
  ref,
) {
  const isDisabled = disabled || loading;
  const btn = (
    <button
      ref={ref}
      type={type ?? "button"}
      className={buttonClass(variant, size, [block && "block", className].filter(Boolean).join(" "))}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      title={isDisabled && disabledReason ? disabledReason : rest.title}
      {...rest}
    >
      {loading ? <Loader2 size={16} className="spin" aria-hidden="true" /> : icon}
      {children}
      {iconRight}
    </button>
  );
  return btn;
});

/** A square button with an icon only; the label is its accessible name and its tooltip. */
export function IconButton({ label, icon, size = "md", variant = "ghost", ...rest }: Omit<ButtonProps, "children"> & { label: string; icon: ReactNode }) {
  return (
    <Tooltip text={label}>
      <Button aria-label={label} variant={variant} size={size} className={`icon-btn ${size === "sm" ? "sm" : ""}`} {...rest}>
        {icon}
      </Button>
    </Tooltip>
  );
}
