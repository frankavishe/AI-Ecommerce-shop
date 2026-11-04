"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Clock, Smartphone, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { Button } from "@/components/ui/button";
import { fmt } from "@/i18n/config";
import { useT } from "@/i18n/client";
import { ApiError } from "@/lib/api/errors";
import type { Order } from "@/lib/api/types";
import { formatDateTime, formatTime } from "@/lib/dates";
import { formatTZS } from "@/lib/money";
import { canPay } from "@/lib/order-status";
import { useOrder } from "@/lib/queries/orders";
import { useSession } from "@/lib/queries/session";
import { OrderStatusBadge, OrderTimeline } from "./order-timeline";
import { PayAgainDialog } from "./pay-again-dialog";

function Totals({ order }: { order: Order }) {
  const { t } = useT();
  return (
    <dl className="flex flex-col gap-1 text-sm">
      <div className="flex justify-between">
        <dt>{t.order.subtotal}</dt>
        <dd className="tabular-nums">{formatTZS(order.subtotal)}</dd>
      </div>
      <div className="flex justify-between">
        <dt>{t.order.deliveryFee}</dt>
        <dd className="tabular-nums">{formatTZS(order.delivery_fee)}</dd>
      </div>
      <div className="mt-1 flex justify-between border-t pt-2 text-base font-semibold">
        <dt>{t.order.total}</dt>
        <dd data-testid="order-total" className="tabular-nums">{formatTZS(order.total)}</dd>
      </div>
    </dl>
  );
}

export function OrderView({ number, pending }: { number: string; pending: boolean }) {
  const { t, locale } = useT();
  const router = useRouter();
  const { data: user, isLoading: sessionLoading } = useSession();
  const { data: order, error, isLoading, refetch } = useOrder(number, Boolean(user), !sessionLoading);
  const { data: paymentError } = useQuery<string | null>({
    queryKey: ["payment-error", number],
    queryFn: () => null,
    staleTime: Infinity,
  });

  const needsLookup = error instanceof ApiError && error.status === 404;
  useEffect(() => {
    if (needsLookup) router.replace(`/track?number=${encodeURIComponent(number)}`);
  }, [needsLookup, number, router]);

  if (sessionLoading || isLoading || needsLookup) return <PanelSkeleton />;
  if (error || !order) {
    return (
      <div className="py-16 text-center">
        <p className="mb-4 text-muted-foreground">{t.common.errorBody}</p>
        <Button onClick={() => refetch()}>{t.common.retry}</Button>
      </div>
    );
  }

  const awaiting = canPay(order.status);
  const paid = Boolean(order.paid_at) || ["paid", "processing", "out_for_delivery", "delivered"].includes(order.status);

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{fmt(t.order.title, { number: order.number })}</h1>
          <p className="text-sm text-muted-foreground">{fmt(t.order.placedOn, { date: formatDateTime(order.placed_at, locale) })}</p>
        </div>
        <OrderStatusBadge status={order.status} />
      </header>

      {awaiting && paymentError && (
        <div role="alert" className="flex gap-3 rounded-xl border border-destructive/30 bg-destructive/10 p-4">
          <TriangleAlert className="mt-0.5 size-5 shrink-0 text-destructive" />
          <div className="flex-1">
            <p className="font-medium">{t.order.paymentProblem}</p>
            <p className="text-sm">{paymentError}</p>
          </div>
        </div>
      )}

      {awaiting && !paymentError && pending && (
        <div className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-950" role="status">
          <Smartphone className="mt-0.5 size-5 shrink-0" />
          <div>
            <p className="font-medium">{t.order.approvePrompt}</p>
            <p className="mt-1 flex items-center gap-1 text-sm">
              <Clock className="size-3.5 animate-pulse" /> {t.order.waiting}
            </p>
          </div>
        </div>
      )}

      {paid && pending && (
        <div className="flex gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-950" role="status">
          <CheckCircle2 className="mt-0.5 size-5 shrink-0" />
          <p className="font-medium">{t.order.paidThanks}</p>
        </div>
      )}

      {awaiting && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4">
          <p className="text-sm text-muted-foreground">{fmt(t.order.payExpires, { time: formatTime(order.expires_at, locale) })}</p>
          <PayAgainDialog order={order} label={pending && !paymentError ? t.order.payAgain : t.order.payNow} />
        </div>
      )}

      <section className="rounded-xl border">
        <h2 className="border-b px-4 py-3 font-semibold">{t.order.items}</h2>
        <ul className="divide-y">
          {order.items.map((item, i) => (
            <li key={`${item.product ?? "x"}-${i}`} className="flex justify-between gap-3 px-4 py-3 text-sm">
              <span>
                {item.quantity} × {item.product_name}
                <span className="block text-muted-foreground tabular-nums">{formatTZS(item.unit_price)}</span>
              </span>
              <span className="font-medium tabular-nums">{formatTZS(item.line_total)}</span>
            </li>
          ))}
        </ul>
        <div className="border-t px-4 py-3">
          <Totals order={order} />
        </div>
      </section>

      <div className="grid gap-6 sm:grid-cols-2">
        <section className="rounded-xl border p-4 text-sm">
          <h2 className="mb-2 font-semibold">{t.order.deliverTo}</h2>
          <p>{order.contact_name}</p>
          <p className="text-muted-foreground">{order.contact_phone}</p>
          <p className="mt-2">{[order.street, order.district, order.region].filter(Boolean).join(", ")}</p>
          {order.notes && <p className="mt-1 text-muted-foreground">{order.notes}</p>}
        </section>
        <section className="rounded-xl border p-4">
          <h2 className="mb-3 font-semibold">{t.order.history}</h2>
          <OrderTimeline events={order.events} />
        </section>
      </div>

      <Button asChild variant="outline" className="self-start">
        <Link href="/products">{t.order.continueShopping}</Link>
      </Button>
    </div>
  );
}
