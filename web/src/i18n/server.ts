import "server-only";
import { cookies, headers } from "next/headers";
import { COOKIE } from "@/lib/auth";
import { dictionaries, pickLocale, type Locale } from "./config";

/** Request-time locale; callers must render inside <Suspense> (Cache Components). */
export async function getLocale(): Promise<Locale> {
  const [jar, hdrs] = await Promise.all([cookies(), headers()]);
  return pickLocale(jar.get(COOKIE.lang)?.value, hdrs.get("accept-language"));
}

export async function getDictionary() {
  const locale = await getLocale();
  return { locale, t: dictionaries[locale] };
}
