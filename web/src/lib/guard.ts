import { decodeSession, isExpired } from "./auth";

export type GuardDecision = { action: "next" } | { action: "redirect"; to: string };

/**
 * UX-only route guard for /admin and /account (research R5). Django enforces every permission;
 * this just avoids rendering pages the user can't use.
 */
export function guard(pathname: string, search: string, access?: string, refresh?: string): GuardDecision {
  const isAdmin = pathname === "/admin" || pathname.startsWith("/admin/");
  const isAccount = pathname === "/account" || pathname.startsWith("/account/");
  if (!isAdmin && !isAccount) return { action: "next" };

  const session = access && !isExpired(access) ? decodeSession(access) : null;
  // An expired access token with a refresh cookie: let the page load; the BFF refreshes on first call.
  const maybeLoggedIn = session !== null || Boolean(refresh);
  const login = `/login?next=${encodeURIComponent(pathname + search)}`;

  if (!maybeLoggedIn) return { action: "redirect", to: login };
  if (isAdmin) {
    const role = session?.role ?? decodeSession(access)?.role;
    if (!role) return { action: "redirect", to: login };
    if (role !== "admin") return { action: "redirect", to: "/forbidden" };
  }
  return { action: "next" };
}

/** A post-login target limited to same-origin paths (no `//host`, no schemes, no backslashes). */
export function safeNext(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return null;
  if (/[\u0000-\u001f]/.test(next)) return null;
  return next;
}
