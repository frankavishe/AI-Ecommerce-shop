import { NextResponse, type NextRequest } from "next/server";
import { forward, type ForwardResult } from "@/lib/bff";
import { applyCookies, jarFrom, upstream } from "@/lib/bff-next";

/** Same-origin proxy to Django: /bff/api/<path> → DJANGO_API_URL/api/<path> (research R2). */
async function handle(req: NextRequest) {
  const rest = req.nextUrl.pathname.replace(/^\/bff\//, "");
  if (!rest.startsWith("api/")) return NextResponse.json({ detail: "Not found." }, { status: 404 });
  const body = ["GET", "HEAD"].includes(req.method) ? null : await req.arrayBuffer();

  let result: ForwardResult;
  try {
    result = await forward(
      {
        method: req.method,
        path: rest.slice("api/".length),
        search: req.nextUrl.search,
        headers: req.headers,
        body,
        jar: jarFrom(req),
      },
      upstream(),
    );
  } catch {
    return NextResponse.json(
      { detail: "The shop is temporarily unavailable. Please try again.", code: "upstream_unavailable" },
      { status: 502 },
    );
  }
  const res = new NextResponse(result.body, { status: result.status, headers: result.headers });
  return applyCookies(res, result.cookies);
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
