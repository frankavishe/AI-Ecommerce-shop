export type Role = "customer" | "admin" | "rider";
export type Session = { role: Role; userId: number; exp?: number };

const ROLES: readonly Role[] = ["customer", "admin", "rider"];

/** httpOnly cookies owned by the BFF (data-model.md). */
export const COOKIE = {
  access: "sa_access",
  refresh: "sa_refresh",
  cart: "sa_cart",
  lang: "sa_lang",
} as const;
export type CookieKey = keyof typeof COOKIE;

const MAX_AGE: Record<CookieKey, number> = {
  access: 30 * 60,
  refresh: 30 * 24 * 60 * 60,
  cart: 60 * 24 * 60 * 60,
  lang: 365 * 24 * 60 * 60,
};

export function cookieOptions(key: CookieKey) {
  return {
    httpOnly: key !== "lang",
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: MAX_AGE[key],
  };
}

function payload(token: string | undefined): Record<string, unknown> | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const json = typeof atob === "function" ? atob(b64) : Buffer.from(b64, "base64").toString("binary");
    const data = JSON.parse(json);
    return data && typeof data === "object" ? data : null;
  } catch {
    return null;
  }
}

/** Decodes (does NOT verify) a JWT for UI decisions. Django verifies every request. */
export function decodeSession(token: string | undefined): Session | null {
  const data = payload(token);
  if (!data) return null;
  const role = data.role as Role;
  const userId = Number(data.user_id);
  if (!ROLES.includes(role) || !Number.isFinite(userId)) return null;
  return { role, userId, exp: typeof data.exp === "number" ? data.exp : undefined };
}

export function isExpired(token: string | undefined, nowMs = Date.now(), skewSeconds = 30): boolean {
  const exp = payload(token)?.exp;
  if (typeof exp !== "number") return true;
  return exp - skewSeconds <= nowMs / 1000;
}

/** Only same-origin relative paths are allowed as post-login targets. */
export function safeNext(next: string | null | undefined, fallback = "/account"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  return next;
}
