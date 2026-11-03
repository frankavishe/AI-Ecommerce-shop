import { describe, expect, it } from "vitest";
import { formatTZS } from "./money";

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
