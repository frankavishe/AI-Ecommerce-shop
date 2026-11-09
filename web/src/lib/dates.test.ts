import { describe, expect, it } from "vitest";
import { formatDateTime, formatTime } from "./dates";

describe("dates", () => {
  it("formats in Dar es Salaam time (UTC+3)", () => {
    expect(formatTime("2026-11-03T09:30:00Z", "en")).toBe("12:30");
    expect(formatDateTime("2026-11-03T22:30:00Z", "en")).toContain("4 Nov 2026");
  });
  it("handles missing or bad input", () => {
    expect(formatDateTime(null, "en")).toBe("—");
    expect(formatTime("nope", "sw")).toBe("—");
  });
});
