import { NextResponse, type NextRequest } from "next/server";
import { currentUser } from "@/lib/bff";
import { applyCookies, jarFrom, upstream } from "@/lib/bff-next";

export async function GET(req: NextRequest) {
  try {
    const result = await currentUser(jarFrom(req), upstream());
    return applyCookies(NextResponse.json(result.body, { status: result.status }), result.cookies);
  } catch {
    return NextResponse.json({ user: null, detail: "The shop is temporarily unavailable." }, { status: 502 });
  }
}
