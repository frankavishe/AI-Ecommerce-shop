import { NextResponse } from "next/server";
import { applyCookies } from "@/lib/bff-next";

export async function POST() {
  return applyCookies(new NextResponse(null, { status: 204 }), [
    { name: "access", value: null },
    { name: "refresh", value: null },
    { name: "cart", value: null },
  ]);
}
