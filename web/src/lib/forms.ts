import type { FieldValues, Path, UseFormGetValues, UseFormSetError } from "react-hook-form";
import { ApiError } from "@/lib/api/errors";

/**
 * Maps DRF field errors onto form fields. Returns the message to show above the submit button
 * when nothing could be mapped (or null when every error landed on a field).
 */
export function applyServerErrors<T extends FieldValues>(
  error: unknown,
  form: { getValues: UseFormGetValues<T>; setError: UseFormSetError<T> },
  fallback: string,
): string | null {
  if (!(error instanceof ApiError)) return fallback;
  const values = form.getValues() as Record<string, unknown>;
  let mapped = false;
  for (const [field, messages] of Object.entries(error.fields ?? {})) {
    if (field in values) {
      form.setError(field as Path<T>, { message: messages[0] });
      mapped = true;
    }
  }
  return mapped ? null : (error.detail ?? fallback);
}
