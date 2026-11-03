import type { ReactNode } from "react";

export const inputClass =
  "h-10 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive";

/** Label + control + hint/error, wired for screen readers via `${id}-hint` / `${id}-error`. */
export function Field({
  id,
  label,
  error,
  hint,
  optional,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  optional?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
        {optional && <span className="font-normal text-muted-foreground"> ({optional})</span>}
      </label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

/** `aria-describedby` for a Field's control. */
export const describedBy = (id: string, hasError: boolean, hasHint = false) =>
  hasError ? `${id}-error` : hasHint ? `${id}-hint` : undefined;
