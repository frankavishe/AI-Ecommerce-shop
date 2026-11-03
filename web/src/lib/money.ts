/**
 * Display-only TZS formatting of API decimal strings ("45000.00").
 * Works on the string digits, so it never rounds; the web never does money arithmetic (FR-005).
 */
export function formatTZS(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const match = /^(-)?(\d+)(?:\.(\d+))?$/.exec(String(value).trim());
  if (!match) return "—";
  const [, minus, whole, frac = ""] = match;
  const grouped = whole.replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const cents = /^0*$/.test(frac) ? "" : `.${frac.padEnd(2, "0")}`;
  return `${minus ? "-" : ""}TSh ${grouped}${cents}`;
}

const ZERO = BigInt(0);
const HUNDRED = BigInt(100);

function toCents(value: string | null | undefined): bigint | null {
  const m = /^(-)?(\d+)(?:\.(\d{1,2}))?$/.exec(String(value ?? "").trim());
  if (!m) return null;
  const cents = BigInt(m[2]) * HUNDRED + BigInt((m[3] ?? "").padEnd(2, "0") || "0");
  return m[1] ? -cents : cents;
}

/**
 * Exact sum of server-provided decimal strings, used only to preview the checkout total
 * (subtotal + region fee) before the order exists. Never sent to the server (FR-005).
 */
export function addMoney(...values: (string | null | undefined)[]): string | null {
  let total = ZERO;
  for (const v of values) {
    const cents = toCents(v);
    if (cents === null) return null;
    total += cents;
  }
  const sign = total < ZERO ? "-" : "";
  const abs = total < ZERO ? -total : total;
  return `${sign}${abs / HUNDRED}.${String(abs % HUNDRED).padStart(2, "0")}`;
}

/** True when the string is a positive-or-zero TZS amount with at most 2 decimals. */
export const isMoney = (value: string) => /^\d+(\.\d{1,2})?$/.test(value.trim());

/** Exact comparison of decimal strings: -1, 0 or 1, or null when either is not a valid amount. */
export function compareMoney(a: string | null | undefined, b: string | null | undefined): -1 | 0 | 1 | null {
  const x = toCents(a);
  const y = toCents(b);
  if (x === null || y === null) return null;
  return x === y ? 0 : x < y ? -1 : 1;
}
