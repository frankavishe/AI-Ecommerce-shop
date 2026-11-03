"use client";

import { useT } from "@/i18n/client";
import type { Order, OrderStatus } from "@/lib/api/types";
import { formatDateTime } from "@/lib/dates";
import { statusTone, TONE_CLASS } from "@/lib/order-status";
import { cn } from "@/lib/utils";

export function OrderStatusBadge({ status }: { status: OrderStatus }) {
  const { t } = useT();
  return (
    <span
      data-testid="order-status"
      className={cn("inline-flex rounded-full border px-3 py-1 text-sm font-medium", TONE_CLASS[statusTone(status)])}
    >
      {t.order.statuses[status]}
    </span>
  );
}

export function OrderTimeline({ events }: { events: Order["events"] }) {
  const { t, locale } = useT();
  const sorted = [...events].sort((a, b) => a.created_at.localeCompare(b.created_at));
  return (
    <ol className="relative flex flex-col gap-4 border-l pl-4">
      {sorted.map((e, i) => (
        <li key={`${e.created_at}-${i}`} className="relative">
          <span
            className={cn(
              "absolute -left-[21px] top-1.5 size-2.5 rounded-full border-2 border-background",
              i === sorted.length - 1 ? "bg-primary" : "bg-muted-foreground/40",
            )}
            aria-hidden
          />
          <p className="text-sm font-medium">{t.order.statuses[e.status]}</p>
          <p className="text-xs text-muted-foreground">{formatDateTime(e.created_at, locale)}</p>
          {e.note && <p className="mt-0.5 text-sm text-muted-foreground">{e.note}</p>}
        </li>
      ))}
    </ol>
  );
}
