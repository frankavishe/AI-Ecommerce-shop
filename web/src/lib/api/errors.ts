const GENERIC = "Something went wrong. Please try again.";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public code?: string,
    public fields?: Record<string, string[]>,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

function strings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(strings);
  if (value && typeof value === "object") return Object.values(value).flatMap(strings);
  return [];
}

/** Normalises `{detail, code}` and DRF field errors into one shape. */
export function toApiError(status: number, body: unknown): ApiError {
  if (body && typeof body === "object" && !Array.isArray(body)) {
    const obj = body as Record<string, unknown>;
    if (typeof obj.detail === "string") {
      return new ApiError(status, obj.detail, typeof obj.code === "string" ? obj.code : undefined);
    }
    const fields: Record<string, string[]> = {};
    let detail: string | undefined;
    for (const [key, value] of Object.entries(obj)) {
      const msgs = strings(value);
      if (!msgs.length) continue;
      if (key === "non_field_errors") detail ??= msgs[0];
      else fields[key] = msgs;
    }
    const keys = Object.keys(fields);
    detail ??= keys.length ? fields[keys[0]][0] : undefined;
    if (detail) return new ApiError(status, detail, undefined, keys.length ? fields : undefined);
  }
  return new ApiError(status, GENERIC);
}
