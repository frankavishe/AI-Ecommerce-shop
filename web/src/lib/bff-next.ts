import "server-only";
import type { NextRequest, NextResponse } from "next/server";
import { COOKIE, cookieOptions } from "./auth";
import type { CookieChange, Jar, Upstream } from "./bff";

export function upstream(): Upstream {
  return { apiUrl: (process.env.DJANGO_API_URL ?? "http://localhost:8000").replace(/\/+$/, ""), fetch };
}

export function jarFrom(req: NextRequest): Jar {
  return {
    access: req.cookies.get(COOKIE.access)?.value,
    refresh: req.cookies.get(COOKIE.refresh)?.value,
    cart: req.cookies.get(COOKIE.cart)?.value,
  };
}

export function applyCookies(res: NextResponse, changes: CookieChange[]): NextResponse {
  for (const { name, value } of changes) {
    if (value === null) res.cookies.set(COOKIE[name], "", { ...cookieOptions(name), maxAge: 0 });
    else res.cookies.set(COOKIE[name], value, cookieOptions(name));
  }
  return res;
}
