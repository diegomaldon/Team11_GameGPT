"use client";

// Small, consistent UI primitives for the Deep Blue Spotlight theme (TM11-142).
// Navy surfaces, one cream accent, pill-shaped controls, solid fills — no gradients.
// Colours come from the tokens in app/globals.css.

import { useEffect, useRef } from "react";
import { Spinner, X } from "./icons";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

// ── Button ──
type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
};

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  const variants = {
    primary:
      "bg-[var(--accent)] text-[var(--on-accent)] hover:bg-[var(--accent-hover)]",
    secondary:
      "border border-[var(--border-strong)] bg-transparent text-[var(--ink)] hover:bg-[var(--raised-2)]",
    ghost: "text-[var(--ink-soft)] hover:bg-[var(--raised)] hover:text-[var(--heading)]",
    danger:
      "border border-rose-300 bg-transparent text-rose-600 hover:bg-rose-50",
  };
  const sizes = {
    sm: "h-10 px-4 text-[13px] gap-1.5",
    md: "h-12 px-6 text-[15px] gap-2",
  };
  return (
    <button
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center rounded-full font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {loading && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  );
}

// ── Card ──
export function Card({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cx(
        "rounded-3xl border border-[var(--border)] bg-[var(--surface)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

// ── Field (label + control + hint/error) ──
export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
}: {
  label: string;
  htmlFor?: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-[13px] font-medium text-[var(--label)]">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-xs text-rose-600">{error}</p>
      ) : hint ? (
        <p className="text-xs text-[var(--ink-faint)]">{hint}</p>
      ) : null}
    </div>
  );
}

const inputCls =
  "h-12 w-full rounded-full border border-[var(--border)] bg-[var(--bg)] px-5 text-[15px] text-[var(--ink)] outline-none transition-colors focus:border-[var(--accent)] disabled:bg-[var(--surface)] disabled:text-[var(--ink-faint)]";

export function TextInput(
  props: React.InputHTMLAttributes<HTMLInputElement>,
) {
  return <input {...props} className={cx(inputCls, props.className)} />;
}

export function Select(
  props: React.SelectHTMLAttributes<HTMLSelectElement>,
) {
  return <select {...props} className={cx(inputCls, "pr-8", props.className)} />;
}

// ── Toggle switch ──
export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cx(
        "relative h-7 w-12 shrink-0 rounded-full transition-colors",
        checked
          ? "bg-[var(--accent)]"
          : "bg-[var(--bg)] ring-1 ring-inset ring-[var(--border-strong)]",
      )}
    >
      <span
        className={cx(
          "absolute left-0 top-1 h-5 w-5 rounded-full transition-transform",
          checked ? "translate-x-6 bg-[var(--on-accent)]" : "translate-x-1 bg-[var(--ink-faint)]",
        )}
      />
    </button>
  );
}

// ── Badge ──
export function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "success" | "accent";
}) {
  const tones = {
    neutral: "bg-[var(--raised-2)] text-[var(--ink-soft)]",
    success: "bg-emerald-50 text-emerald-700",
    accent: "border border-[var(--border-strong)] text-[var(--label)]",
  };
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold",
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}

// ── Avatar (initials) ──
export function Avatar({
  name,
  size = 36,
}: {
  name: string;
  size?: number;
}) {
  const initials = name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-full bg-[var(--accent)] font-semibold text-[var(--on-accent)]"
      style={{ width: size, height: size, fontSize: size * 0.4 }}
      aria-hidden
    >
      {initials}
    </span>
  );
}

// ── Modal ──
export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);

  // onClose is almost always an inline arrow or a function declared in the caller's
  // body, so its identity changes on every parent render. Holding it in a ref keeps
  // the effect below depending on `open` alone.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  // Deps are [open] on purpose. With onClose in the list this effect re-ran on every
  // keystroke in a modal that renders a controlled input — each run called
  // ref.current?.focus(), which moved focus off the field and made typing anything
  // longer than one character impossible.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCloseRef.current();
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    ref.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-[rgb(2_5_12/0.72)] p-0 sm:items-center sm:p-4"
      onMouseDown={onClose}
    >
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-md animate-fade-up rounded-t-3xl border border-[var(--border)] bg-[var(--surface)] shadow-lift outline-none sm:rounded-3xl"
      >
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
          <h2 className="font-display text-2xl">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-11 w-11 items-center justify-center rounded-full text-[var(--ink-faint)] hover:bg-[var(--raised)] hover:text-[var(--heading)]"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="px-5 py-5">{children}</div>
        {footer && (
          <div className="flex justify-end gap-2 border-t border-[var(--border)] px-5 py-4">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Empty state ──
export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center rounded-3xl border border-dashed border-[var(--border-strong)] bg-[var(--surface)] px-6 py-12 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--raised-2)] text-[var(--ink-faint)]">
        {icon}
      </span>
      <p className="mt-4 font-display text-xl">{title}</p>
      <p className="mt-1 max-w-xs text-sm text-[var(--ink-faint)]">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// ── Page header ──
export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-4xl leading-[1.05] sm:text-[56px]">{title}</h1>
        {subtitle && (
          <p className="mt-3 max-w-xl text-base leading-relaxed text-[var(--ink-faint)]">
            {subtitle}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}
