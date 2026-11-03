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
