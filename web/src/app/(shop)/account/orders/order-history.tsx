"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { OrderStatusBadge } from "@/components/shop/order-timeline";
import { Pagination } from "@/components/shop/pagination";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n/client";
import { bff } from "@/lib/api/client";
import type { OrderSummary, Paginated } from "@/lib/api/types";
import { formatDateTime } from "@/lib/dates";
import { formatTZS } from "@/lib/money";

export function OrderHistory({ page }: { page: number }) {
  const { t, locale } = useT();
  const orders = useQuery({
    queryKey: ["my-orders", page],
    queryFn: () => bff<Paginated<OrderSummary>>(`orders/${page > 1 ? `?page=${page}` : ""}`),
    placeholderData: keepPreviousData,
  });

  if (orders.isLoading) return <PanelSkeleton />;
  if (orders.isError || !orders.data) {
    return (
      <div className="flex flex-col items-start gap-3">
        <p>{t.common.errorBody}</p>
        <Button variant="outline" onClick={() => orders.refetch()}>
          {t.common.retry}
        </Button>
      </div>
    );
  }

  const { results, count } = orders.data;
  if (results.length === 0) {
    return (
      <div className="flex flex-col items-center gap-4 rounded-xl border border-dashed p-8 text-center">
        <p className="text-muted-foreground">{t.account.noOrders}</p>
        <Button asChild>
          <Link href="/products">{t.cart.continueShopping}</Link>
        </Button>
      </div>
    );
  }

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">{t.account.orders}</h2>
      <ul className="flex flex-col divide-y rounded-xl border">
        {results.map((o) => (
          <li key={o.number} className="relative flex flex-wrap items-center gap-x-4 gap-y-2 p-4 hover:bg-accent/50">
            <div className="min-w-0 flex-1 basis-40">
              <Link href={`/orders/${o.number}`} className="font-medium after:absolute after:inset-0">
                {o.number}
              </Link>
              <p className="text-sm text-muted-foreground">{formatDateTime(o.placed_at, locale)}</p>
            </div>
            <OrderStatusBadge status={o.status ?? "awaiting_payment"} />
            <span className="ml-auto w-28 text-right font-medium tabular-nums">{formatTZS(o.total)}</span>
            <ChevronRight className="hidden size-4 text-muted-foreground sm:block" aria-hidden />
          </li>
        ))}
      </ul>
      <Pagination
        count={count}
        page={page}
        params={{}}
        pathname="/account/orders"
        labels={{ previous: t.common.previous, next: t.common.next, page: t.common.page }}
      />
    </section>
  );
}
