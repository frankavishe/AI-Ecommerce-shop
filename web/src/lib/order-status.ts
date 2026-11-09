import type { OrderStatus } from "./api/types";

export const ORDER_STATUSES: readonly OrderStatus[] = [
  "awaiting_payment", "paid", "processing", "out_for_delivery", "delivered", "cancelled", "expired", "needs_review",
];

export type Tone = "pending" | "success" | "info" | "danger" | "muted";

const TONES: Record<OrderStatus, Tone> = {
  awaiting_payment: "pending",
  paid: "success",
  processing: "info",
  out_for_delivery: "info",
  delivered: "success",
  cancelled: "muted",
  expired: "muted",
  needs_review: "danger",
};

export const statusTone = (s: OrderStatus): Tone => TONES[s];
export const canPay = (s: OrderStatus) => s === "awaiting_payment";
export const shouldPoll = (s: OrderStatus) => s === "awaiting_payment";

export const TONE_CLASS: Record<Tone, string> = {
  pending: "bg-amber-100 text-amber-900 border-amber-200",
  success: "bg-emerald-100 text-emerald-900 border-emerald-200",
  info: "bg-sky-100 text-sky-900 border-sky-200",
  danger: "bg-red-100 text-red-900 border-red-200",
  muted: "bg-muted text-muted-foreground border-border",
};

/**
 * Mirrors backend apps/orders/services.py TRANSITIONS. Only used to suggest choices in the admin
 * status dialog; Django decides and answers `invalid_transition` for anything else.
 */
export const NEXT_STATUSES: Record<OrderStatus, readonly OrderStatus[]> = {
  awaiting_payment: ["paid", "cancelled", "expired", "needs_review"],
  paid: ["processing", "cancelled", "needs_review"],
  processing: ["out_for_delivery", "cancelled"],
  out_for_delivery: ["delivered", "cancelled"],
  needs_review: ["paid", "cancelled"],
  expired: ["needs_review"],
  delivered: [],
  cancelled: [],
};
