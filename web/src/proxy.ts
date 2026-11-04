import { NextResponse, type NextRequest } from "next/server";
import { COOKIE } from "@/lib/auth";
import { guard } from "@/lib/guard";

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const decision = guard(
    pathname,
    search,
    request.cookies.get(COOKIE.access)?.value,
    request.cookies.get(COOKIE.refresh)?.value,
  );
  if (decision.action === "redirect") return NextResponse.redirect(new URL(decision.to, request.url));
  return NextResponse.next();
}

export const config = {
  matcher: ["/admin/:path*", "/account/:path*"],
};
