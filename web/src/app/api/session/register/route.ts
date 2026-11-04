import { NextResponse, type NextRequest } from "next/server";
import { register } from "@/lib/bff";
import { applyCookies, jarFrom, upstream } from "@/lib/bff-next";

const FIELDS = ["username", "password", "email", "first_name", "last_name", "phone", "preferred_language"] as const;

export async function POST(req: NextRequest) {
  const raw = (await req.json().catch(() => ({}))) as Record<string, unknown>;
  const data: Record<string, string> = {};
  for (const key of FIELDS) if (typeof raw[key] === "string") data[key] = raw[key] as string;
  try {
    const result = await register(
      { ...data, username: data.username ?? "", password: data.password ?? "" },
      jarFrom(req),
      upstream(),
    );
    return applyCookies(NextResponse.json(result.body, { status: result.status }), result.cookies);
  } catch {
    return NextResponse.json({ detail: "The shop is temporarily unavailable." }, { status: 502 });
  }
}
