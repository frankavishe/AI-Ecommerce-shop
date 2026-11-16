import { describe, expect, it } from "vitest";
import { formatCountdown } from "./whatsapp-link-card";

describe("formatCountdown", () => {
  it("shows minutes and zero-padded seconds", () => {
    expect(formatCountdown(10 * 60_000)).toBe("10:00");
    expect(formatCountdown(65_000)).toBe("1:05");
    expect(formatCountdown(9_000)).toBe("0:09");
  });

  it("rounds partial seconds up and never goes negative", () => {
    expect(formatCountdown(59_001)).toBe("1:00");
    expect(formatCountdown(0)).toBe("0:00");
    expect(formatCountdown(-5_000)).toBe("0:00");
  });
});
