import { NextResponse, type NextRequest } from "next/server";
import { COOKIE, cookieOptions } from "@/lib/auth";
import { isLocale } from "@/i18n/config";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as { lang?: unknown };
  if (!isLocale(body.lang)) return NextResponse.json({ detail: "Unknown language." }, { status: 400 });
  const res = new NextResponse(null, { status: 204 });
  res.cookies.set(COOKIE.lang, body.lang, cookieOptions("lang"));
  return res;
}
