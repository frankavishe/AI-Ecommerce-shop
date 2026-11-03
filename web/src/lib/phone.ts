/** Tanzanian mobile number as typed at checkout (spaces/dashes removed first). */
export const TZ_PHONE = /^(\+?255|0)[67]\d{8}$/;

export const stripPhone = (v: string) => v.replace(/[\s-]/g, "");

/** `0754 222 333` / `255754222333` / `+255754222333` → `+255754222333` (the user API stores E.164). */
export function toE164(v: string): string {
  const s = stripPhone(v);
  if (s.startsWith("+")) return s;
  if (s.startsWith("255")) return `+${s}`;
  if (s.startsWith("0")) return `+255${s.slice(1)}`;
  return s;
}
