import { en, type Dictionary } from "./en";
import { sw } from "./sw";

export type Locale = "en" | "sw";
export const LOCALES: readonly Locale[] = ["en", "sw"];
export const dictionaries: Record<Locale, Dictionary> = { en, sw };
export type { Dictionary };

export function isLocale(v: unknown): v is Locale {
  return v === "en" || v === "sw";
}

/** Cookie wins; otherwise Swahili when the browser prefers it over English (research R6). */
export function pickLocale(cookie: string | undefined, acceptLanguage: string | null | undefined): Locale {
  if (isLocale(cookie)) return cookie;
  const prefs = (acceptLanguage ?? "")
    .split(",")
    .map((part) => {
      const [tag, q] = part.trim().split(";q=");
      return { lang: tag.toLowerCase().slice(0, 2), q: q ? Number(q) : 1 };
    })
    .filter((p) => p.lang === "sw" || p.lang === "en")
    .sort((a, b) => b.q - a.q);
  return prefs[0]?.lang === "sw" ? "sw" : "en";
}

/** Replaces {name} placeholders. */
export function fmt(template: string, vars: Record<string, string | number> = {}): string {
  return template.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

/** Swahili content field when the locale is sw and the value is non-empty, else the English one. */
export function localized(locale: Locale, english: string | undefined | null, swahili: string | undefined | null) {
  return locale === "sw" && swahili?.trim() ? swahili : (english ?? "");
}
