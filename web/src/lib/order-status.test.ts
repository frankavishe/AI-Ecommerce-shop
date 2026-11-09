import { describe, expect, it } from "vitest";
import { canPay, NEXT_STATUSES, ORDER_STATUSES, shouldPoll, statusTone } from "./order-status";
import { en } from "@/i18n/en";

describe("order status", () => {
  it("covers all 8 statuses with a label and tone", () => {
    expect(ORDER_STATUSES).toEqual([
      "awaiting_payment", "paid", "processing", "out_for_delivery", "delivered", "cancelled", "expired", "needs_review",
    ]);
    for (const s of ORDER_STATUSES) {
      expect(en.order.statuses[s]).toBeTruthy();
      expect(["pending", "success", "info", "danger", "muted"]).toContain(statusTone(s));
    }
  });
  it("only allows paying and polling while awaiting payment", () => {
    for (const s of ORDER_STATUSES) {
      expect(canPay(s)).toBe(s === "awaiting_payment");
      expect(shouldPoll(s)).toBe(s === "awaiting_payment");
    }
  });
});

describe("NEXT_STATUSES", () => {
  it("covers every status and only points at known statuses", () => {
    for (const s of ORDER_STATUSES) {
      expect(NEXT_STATUSES[s]).toBeDefined();
      for (const n of NEXT_STATUSES[s]) expect(ORDER_STATUSES).toContain(n);
      expect(NEXT_STATUSES[s]).not.toContain(s);
    }
  });

  it("treats delivered and cancelled as final", () => {
    expect(NEXT_STATUSES.delivered).toEqual([]);
    expect(NEXT_STATUSES.cancelled).toEqual([]);
  });
});
