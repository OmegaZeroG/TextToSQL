import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "../../lib/cn";
import Spinner from "./Spinner";

type Variant = "primary" | "outline" | "ghost" | "danger";
type Size = "md" | "sm" | "icon";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

const base =
  "inline-flex items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap select-none touch-manipulation " +
  "transition-[background-color,border-color,color,transform,box-shadow] duration-150 " +
  "active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50";

const variants: Record<Variant, string> = {
  primary: "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90",
  outline: "border border-border bg-card text-foreground hover:bg-muted",
  ghost: "text-muted-foreground hover:bg-muted hover:text-foreground",
  danger: "bg-destructive text-background hover:bg-destructive/90",
};

// Mobile targets are at least 44px tall; they tighten up on larger screens.
const sizes: Record<Size, string> = {
  md: "h-11 px-4 text-sm sm:h-10",
  sm: "h-10 px-3 text-sm sm:h-8",
  icon: "size-11 sm:size-10",
};

const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  {
    variant = "outline",
    size = "md",
    loading = false,
    className,
    children,
    disabled,
    type = "button",
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(base, variants[variant], sizes[size], className)}
      {...rest}
    >
      {loading && <Spinner />}
      {children}
    </button>
  );
});

export default Button;
