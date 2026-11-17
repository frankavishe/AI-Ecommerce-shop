import type { DeliveryStatus } from "@/lib/api/types";
import { DELIVERY_LABELS, deliveryTone } from "@/lib/delivery-status";
import { TONE_CLASS } from "@/lib/order-status";
import { cn } from "@/lib/utils";

export function DeliveryBadge({ status, testId }: { status: DeliveryStatus; testId?: string }) {
  return (
    <span
      data-testid={testId}
      className={cn(
        "inline-flex whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium",
        TONE_CLASS[deliveryTone(status)],
      )}
    >
      {DELIVERY_LABELS[status]}
    </span>
  );
}
