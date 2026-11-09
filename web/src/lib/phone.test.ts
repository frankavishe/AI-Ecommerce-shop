import { describe, expect, it } from "vitest";
import { stripPhone, toE164, TZ_PHONE } from "./phone";

describe("phone", () => {
  it("accepts Tanzanian mobile numbers after stripping spaces and dashes", () => {
    for (const ok of ["0712 345 678", "0612-345-678", "+255712345678", "255754222333"]) {
      expect(TZ_PHONE.test(stripPhone(ok))).toBe(true);
    }
    for (const bad of ["0812345678", "071234567", "+254712345678", ""]) {
      expect(TZ_PHONE.test(stripPhone(bad))).toBe(false);
    }
  });

  it("normalises to E.164", () => {
    expect(toE164("0754 222 333")).toBe("+255754222333");
    expect(toE164("255754222333")).toBe("+255754222333");
    expect(toE164("+255 754 222 333")).toBe("+255754222333");
  });
});
