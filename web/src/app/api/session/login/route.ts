import { NextResponse, type NextRequest } from "next/server";
import { login } from "@/lib/bff";
import { applyCookies, jarFrom, upstream } from "@/lib/bff-next";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as { username?: unknown; password?: unknown };
  const username = typeof body.username === "string" ? body.username : "";
  const password = typeof body.password === "string" ? body.password : "";
  if (!username || !password) {
    return NextResponse.json({ detail: "Invalid username or password.", code: "invalid_credentials" }, { status: 401 });
  }
  try {
    const result = await login({ username, password }, jarFrom(req), upstream());
    return applyCookies(NextResponse.json(result.body, { status: result.status }), result.cookies);
  } catch {
    return NextResponse.json({ detail: "The shop is temporarily unavailable." }, { status: 502 });
  }
}
