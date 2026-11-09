"use client";

import { AlertTriangle } from "lucide-react";
import Link from "next/link";
import { PageHeader, StatusBadge, tableWrap, td, th } from "@/components/admin/ui";
import { Skeleton } from "@/components/ui/skeleton";
import type { OrderStatus } from "@/lib/api/types";
import { useLowStock, useOrderCount } from "@/lib/queries/admin";

const CARDS: { status: OrderStatus; hint: string }[] = [
  { status: "awaiting_payment", hint: "Waiting for the customer to pay" },
  { status: "paid", hint: "Ready to pack" },
  { status: "processing", hint: "Being prepared" },
];

function CountCard({ status, hint }: { status: OrderStatus; hint: string }) {
  const count = useOrderCount(status);
  return (
    <Link
      href={`/admin/orders?status=${status}`}
      className="flex flex-col gap-2 rounded-xl border bg-card p-5 transition-colors hover:border-primary"
    >
      <StatusBadge status={status} />
      {count.isLoading ? (
        <Skeleton className="h-9 w-16" />
      ) : (
        <span data-testid={`count-${status}`} className="text-3xl font-semibold tabular-nums">
          {count.data ?? "—"}
        </span>
      )}
      <span className="text-sm text-muted-foreground">{hint}</span>
    </Link>
  );
}

export default function AdminDashboard() {
  const low = useLowStock();
  return (
    <>
      <PageHeader title="Dashboard" description="Orders that need attention and stock running low." />
      <section className="grid gap-4 sm:grid-cols-3" aria-label="Orders by status">
        {CARDS.map((c) => (
          <CountCard key={c.status} {...c} />
        ))}
      </section>
      <section className="flex flex-col gap-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          <AlertTriangle className="size-4 text-amber-600" aria-hidden />
          Low stock
        </h2>
        <div className={tableWrap}>
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/50">
              <tr>
                <th className={th}>Product</th>
                <th className={th}>SKU</th>
                <th className={`${th} text-right`}>Stock</th>
                <th className={`${th} text-right`}>Alert at</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {low.isLoading && (
                <tr>
                  <td colSpan={4} className="p-4">
                    <Skeleton className="h-6 w-full" />
                  </td>
                </tr>
              )}
              {low.data?.length === 0 && (
                <tr>
                  <td colSpan={4} className="p-6 text-center text-muted-foreground">
                    Every active product is above its alert level.
                  </td>
                </tr>
              )}
              {low.data?.map((p) => (
                <tr key={p.id}>
                  <td className={td}>
                    <Link href={`/admin/products/${p.slug}`} className="font-medium hover:underline">
                      {p.name}
                    </Link>
                  </td>
                  <td className={`${td} text-muted-foreground`}>{p.sku || "—"}</td>
                  <td className={`${td} text-right font-medium tabular-nums ${p.stock === 0 ? "text-destructive" : ""}`}>{p.stock}</td>
                  <td className={`${td} text-right tabular-nums text-muted-foreground`}>{p.low_stock_threshold}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {low.isError && <p className="text-sm text-destructive">Could not load low-stock products.</p>}
      </section>
    </>
  );
}
