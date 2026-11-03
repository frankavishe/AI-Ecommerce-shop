"use client";

import { Search, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { EmptyRow, ErrorState, PageHeader, StatusBadge, statusLabel, tableWrap, td, th, useUrlParams } from "@/components/admin/ui";
import { inputClass } from "@/components/shop/form-field";
import { Pagination } from "@/components/shop/pagination";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime } from "@/lib/dates";
import { formatTZS } from "@/lib/money";
import { ORDER_STATUSES } from "@/lib/order-status";
import { toQuery, useAdminOrders } from "@/lib/queries/admin";

const KEYS = ["status", "paid", "placed_after", "placed_before", "search"] as const;

export default function AdminOrdersPage() {
  const { values, page, set, raw } = useUrlParams(KEYS);
  const orders = useAdminOrders(toQuery({ ...values, page: page > 1 ? String(page) : undefined }));
  const [search, setSearch] = useState(values.search);
  const filtered = KEYS.some((k) => values[k]);
  const field = `${inputClass} w-auto`;

  return (
    <>
      <PageHeader title="Orders" description={orders.data ? `${orders.data.count} orders` : undefined} />

      <div className="flex flex-wrap items-end gap-2">
        <form
          role="search"
          className="relative min-w-52 flex-1"
          onSubmit={(e) => {
            e.preventDefault();
            set({ search: search.trim() });
          }}
        >
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            aria-label="Search orders"
            placeholder="Order number, name or phone"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={`${inputClass} pl-9`}
          />
        </form>
        <select aria-label="Status" className={field} value={values.status} onChange={(e) => set({ status: e.target.value })}>
          <option value="">All statuses</option>
          {ORDER_STATUSES.map((s) => (
            <option key={s} value={s}>
              {statusLabel(s)}
            </option>
          ))}
        </select>
        <select aria-label="Payment" className={field} value={values.paid} onChange={(e) => set({ paid: e.target.value })}>
          <option value="">Paid and unpaid</option>
          <option value="true">Paid</option>
          <option value="false">Unpaid</option>
        </select>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          From
          <input type="date" className={field} value={values.placed_after} onChange={(e) => set({ placed_after: e.target.value })} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Before
          <input type="date" className={field} value={values.placed_before} onChange={(e) => set({ placed_before: e.target.value })} />
        </label>
        {filtered && (
          <Button
            variant="ghost"
            onClick={() => {
              setSearch("");
              set({ status: "", paid: "", placed_after: "", placed_before: "", search: "" });
            }}
          >
            <X className="size-4" />
            Clear
          </Button>
        )}
      </div>

      {orders.isError ? (
        <ErrorState onRetry={() => orders.refetch()} />
      ) : (
        <div className={tableWrap} aria-busy={orders.isFetching}>
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b bg-muted/50">
              <tr>
                <th className={th}>Order</th>
                <th className={th}>Placed</th>
                <th className={th}>Customer</th>
                <th className={th}>Region</th>
                <th className={th}>Status</th>
                <th className={`${th} text-right`}>Total</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {orders.isLoading &&
                Array.from({ length: 5 }, (_, i) => (
                  <tr key={i}>
                    <td colSpan={6} className="p-3">
                      <Skeleton className="h-6 w-full" />
                    </td>
                  </tr>
                ))}
              {orders.data?.results.length === 0 && <EmptyRow colSpan={6}>No orders match these filters.</EmptyRow>}
              {orders.data?.results.map((o) => (
                <tr key={o.number} className="hover:bg-muted/40">
                  <td className={td}>
                    <Link href={`/admin/orders/${o.number}`} className="font-medium text-primary hover:underline">
                      {o.number}
                    </Link>
                  </td>
                  <td className={`${td} whitespace-nowrap text-muted-foreground`}>{formatDateTime(o.placed_at, "en")}</td>
                  <td className={td}>
                    <span className="block">{o.contact_name}</span>
                    <span className="block text-xs text-muted-foreground">{o.contact_phone}</span>
                  </td>
                  <td className={`${td} text-muted-foreground`}>{o.region}</td>
                  <td className={td}>
                    <StatusBadge status={o.status ?? "awaiting_payment"} />
                  </td>
                  <td className={`${td} text-right font-medium tabular-nums`}>{formatTZS(o.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {orders.data && (
        <Pagination
          count={orders.data.count}
          page={page}
          params={Object.fromEntries([...raw.entries()].filter(([k]) => k !== "page"))}
          pathname="/admin/orders"
          labels={{ previous: "Previous", next: "Next", page: "Page {page} of {pages}" }}
        />
      )}
    </>
  );
}
