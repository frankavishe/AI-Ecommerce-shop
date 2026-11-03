import { describe, expect, it } from "vitest";
import { addMoney, compareMoney, formatTZS, isMoney } from "./money";

describe("formatTZS", () => {
  it("drops .00 and groups thousands", () => {
    expect(formatTZS("45000.00")).toBe("TSh 45,000");
    expect(formatTZS("1234567.00")).toBe("TSh 1,234,567");
  });
  it("keeps non-zero cents", () => {
    expect(formatTZS("1234.50")).toBe("TSh 1,234.50");
    expect(formatTZS("0.05")).toBe("TSh 0.05");
  });
  it("handles zero, integers and negatives", () => {
    expect(formatTZS("0.00")).toBe("TSh 0");
    expect(formatTZS("3000")).toBe("TSh 3,000");
    expect(formatTZS("-2500.00")).toBe("-TSh 2,500");
  });
  it("is exact for values floats would round", () => {
    expect(formatTZS("9007199254740993.00")).toBe("TSh 9,007,199,254,740,993");
  });
  it("returns an em dash for missing or malformed input", () => {
    expect(formatTZS(null)).toBe("—");
    expect(formatTZS(undefined)).toBe("—");
    expect(formatTZS("abc")).toBe("—");
  });
});


describe("addMoney (display-only checkout estimate)", () => {
  it("adds decimal strings exactly", () => {
    expect(addMoney("45000.00", "3000.00")).toBe("48000.00");
    expect(addMoney("0.10", "0.20")).toBe("0.30");
    expect(addMoney("9007199254740993.00", "1.00")).toBe("9007199254740994.00");
    expect(addMoney("1234.5", "0")).toBe("1234.50");
  });
  it("returns null for malformed input", () => {
    expect(addMoney("abc", "1.00")).toBeNull();
    expect(addMoney(undefined, "1.00")).toBeNull();
  });
});

describe("compareMoney / isMoney", () => {
  it("compares exactly", () => {
    expect(compareMoney("15000", "12000.00")).toBe(1);
    expect(compareMoney("0.10", "0.1")).toBe(0);
    expect(compareMoney("9999.99", "10000")).toBe(-1);
    expect(compareMoney("abc", "1")).toBeNull();
  });

  it("validates amounts", () => {
    expect(isMoney("12000")).toBe(true);
    expect(isMoney("12000.5")).toBe(true);
    expect(isMoney("12000.555")).toBe(false);
    expect(isMoney("-5")).toBe(false);
    expect(isMoney("")).toBe(false);
  });
});
