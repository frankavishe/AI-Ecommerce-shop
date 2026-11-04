"use client";

import createClient from "openapi-fetch";
import type { paths } from "./schema";
import { toApiError } from "./errors";

/** Browser client. Calls go through the same-origin BFF (/bff/api/...), which adds auth and cart cookies. */
export const api = createClient<paths>({ baseUrl: "/bff" });

/** Unwraps an openapi-fetch result, throwing ApiError on non-2xx. */
export async function must<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok) throw toApiError(response.status, error);
  return data as T;
}

/** Raw JSON call for endpoints whose responses the schema under-describes. */
export async function bff<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const res = await fetch(`/bff/api/${path.replace(/^\/+/, "")}`, {
    ...rest,
    headers: json !== undefined ? { "content-type": "application/json", ...rest.headers } : rest.headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw toApiError(res.status, body);
  return body as T;
}
