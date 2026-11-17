import type { DeliveryStatus } from "./api/types";
import type { Tone } from "./order-status";

export const DELIVERY_STATUSES: readonly DeliveryStatus[] = [
  "waiting", "assigned", "picked_up", "on_the_way", "delivered", "failed", "cancelled",
];

/** Admin is English-only. */
export const DELIVERY_LABELS: Record<DeliveryStatus, string> = {
  waiting: "Waiting for a rider",
  assigned: "Assigned",
  picked_up: "Picked up",
  on_the_way: "On the way",
  delivered: "Delivered",
  failed: "Failed",
  cancelled: "Cancelled",
};

const TONES: Record<DeliveryStatus, Tone> = {
  waiting: "pending",
  assigned: "info",
  picked_up: "info",
  on_the_way: "info",
  delivered: "success",
  failed: "danger",
  cancelled: "muted",
};

export const deliveryTone = (s: DeliveryStatus): Tone => TONES[s];

/** Mirrors backend apps/delivery/services.py; the server decides. */
export const canAssign = (s: DeliveryStatus) => s === "waiting" || s === "assigned";
export const canUnassign = (s: DeliveryStatus) => s === "assigned";
export const OVERRIDES: Partial<Record<DeliveryStatus, readonly ("picked_up" | "on_the_way" | "delivered" | "failed")[]>> = {
  assigned: ["picked_up", "on_the_way", "delivered"],
  picked_up: ["on_the_way", "delivered", "failed"],
  on_the_way: ["delivered", "failed"],
};

export const DELIVERY_ERRORS: Record<string, string> = {
  stale: "Someone changed this delivery meanwhile. The page now shows its current state.",
  rider_unavailable: "That rider can't take deliveries right now (unavailable or deactivated).",
  invalid_transition: "That change isn't possible from the current status.",
  reason_required: "Say why the delivery failed.",
  exists: "This order already has a delivery.",
  not_deliverable: "Only paid or processing orders can be delivered.",
  use_deliveries: "This order has a delivery: move it from the delivery page.",
};
