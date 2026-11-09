"use server";

import { updateTag } from "next/cache";
import { cookies } from "next/headers";
import { COOKIE, decodeSession } from "@/lib/auth";

/**
 * Expires the storefront's cached catalog after an admin edit so the shop shows it at once
 * (read-your-own-writes). Django already enforced the edit; this only gates cache churn.
 */
export async function refreshCatalog(slug?: string) {
  const jar = await cookies();
  const session = decodeSession(jar.get(COOKIE.access)?.value);
  if (session?.role !== "admin") return;
  updateTag("catalog");
  if (slug) updateTag(`product:${slug}`);
}
