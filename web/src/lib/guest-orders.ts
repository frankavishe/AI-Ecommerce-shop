/** Per-tab guest proof (order number → phone) and the card-return target (research R8, R9). */
const ORDERS = "sa_guest_orders";
const LAST = "sa_last_order";

function read(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string) {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    // Private mode or blocked storage: guests can still use /track.
  }
}

function orders(): Record<string, string> {
  try {
    const data = JSON.parse(read(ORDERS) ?? "{}");
    return data && typeof data === "object" ? data : {};
  } catch {
    return {};
  }
}

export function rememberGuestOrder(number: string, phone: string) {
  write(ORDERS, JSON.stringify({ ...orders(), [number]: phone }));
}

export function getGuestPhone(number: string): string | null {
  const phone = orders()[number];
  return typeof phone === "string" ? phone : null;
}

export function setLastOrder(number: string) {
  write(LAST, number);
}

export function getLastOrder(): string | null {
  return read(LAST);
}
