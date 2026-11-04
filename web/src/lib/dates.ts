import type { Locale } from "@/i18n/config";

const TZ = "Africa/Dar_es_Salaam";

/** Business time is Dar es Salaam regardless of the viewer's device (Constitution I). */
export function formatDateTime(iso: string | null | undefined, locale: Locale): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat(locale === "sw" ? "sw-TZ" : "en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: TZ,
  }).format(d);
}

export function formatTime(iso: string | null | undefined, locale: Locale): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat(locale === "sw" ? "sw-TZ" : "en-GB", { timeStyle: "short", timeZone: TZ }).format(d);
}
