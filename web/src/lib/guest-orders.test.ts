import { beforeEach, describe, expect, it, vi } from "vitest";
import { getGuestPhone, getLastOrder, rememberGuestOrder, setLastOrder } from "./guest-orders";

describe("guest orders", () => {
  beforeEach(() => sessionStorage.clear());

  it("remembers phone per order number", () => {
    rememberGuestOrder("K7Q2M9XD", "+255712345678");
    rememberGuestOrder("AB12CD34", "+255754000111");
    expect(getGuestPhone("K7Q2M9XD")).toBe("+255712345678");
    expect(getGuestPhone("AB12CD34")).toBe("+255754000111");
    expect(getGuestPhone("NOPE")).toBeNull();
  });

  it("stores the last order for the card return page", () => {
    expect(getLastOrder()).toBeNull();
    setLastOrder("K7Q2M9XD");
    expect(getLastOrder()).toBe("K7Q2M9XD");
  });

  it("survives corrupt or unavailable storage", () => {
    sessionStorage.setItem("sa_guest_orders", "{not json");
    expect(getGuestPhone("X")).toBeNull();
    rememberGuestOrder("X", "+255700000000");
    expect(getGuestPhone("X")).toBe("+255700000000");

    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(getGuestPhone("X")).toBeNull();
    expect(getLastOrder()).toBeNull();
    spy.mockRestore();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => rememberGuestOrder("Y", "+255700000001")).not.toThrow();
    expect(() => setLastOrder("Y")).not.toThrow();
    vi.restoreAllMocks();
  });
});
