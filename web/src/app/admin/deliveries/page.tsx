"use client";

import { AlertTriangle, X } from "lucide-react";
import Link from "next/link";
import { EmptyRow, ErrorState, PageHeader, plural, tableWrap, td, th, useUrlParams } from "@/components/admin/ui";
import { inputClass } from "@/components/shop/form-field";
import { Pagination } from "@/components/shop/pagination";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime } from "@/lib/dates";
import { DELIVERY_LABELS, DELIVERY_STATUSES } from "@/lib/delivery-status";
import { toQuery, useAdminRegions } from "@/lib/queries/admin";
import { useDeliveries, useRiderOptions } from "@/lib/queries/delivery";
import { cn } from "@/lib/utils";
import { DeliveryBadge } from "./delivery-badge";

const KEYS = ["status", "region", "rider", "attention"] as const;

export default function AdminDeliveriesPage() {
  const { values, page, set, raw } = useUrlParams(KEYS);
  const deliveries = useDeliveries(toQuery({ ...values, page: page > 1 ? String(page) : undefined }));
  const regions = useAdminRegions();
  const riders = useRiderOptions();
  const filtered = KEYS.some((k) => values[k]);
  const field = cn(inputClass, "w-auto");

  return (
    <>
      <PageHeader
        title="Deliveries"
        description={
          deliveries.data ? `${deliveries.data.count} ${deliveries.data.count === 1 ? "delivery" : "deliveries"}` : undefined
        }
      />

      <div className="flex flex-wrap items-end gap-2">
        <select aria-label="Status" className={field} value={values.status} onChange={(e) => set({ status: e.target.value })}>
          <option value="">All statuses</option>
          {DELIVERY_STATUSES.map((s) => (
            <option key={s} value={s}>
              {DELIVERY_LABELS[s]}
            </option>
          ))}
        </select>
        <select aria-label="Region" className={field} value={values.region} onChange={(e) => set({ region: e.target.value })}>
          <option value="">All regions</option>
          {regions.data?.map((r) => (
            <option key={r.id} value={r.name}>
              {r.name}
            </option>
          ))}
        </select>
        <select aria-label="Rider" className={field} value={values.rider} onChange={(e) => set({ rider: e.target.value })}>
          <option value="">All riders</option>
          {riders.data?.map((r) => (
            <option key={r.user_id} value={String(r.user_id)}>
              {`${r.first_name} ${r.last_name}`.trim()}
            </option>
          ))}
        </select>
        <label className="flex h-10 items-center gap-2 rounded-md border px-3 text-sm">
          <input
            type="checkbox"
            checked={values.attention === "1"}
            onChange={(e) => set({ attention: e.target.checked ? "1" : "" })}
          />
          Needs attention
        </label>
        {filtered && (
          <Button variant="ghost" onClick={() => set({ status: "", region: "", rider: "", attention: "" })}>
            <X className="size-4" />
            Clear
          </Button>
        )}
      </div>

      {deliveries.isError ? (
        <ErrorState onRetry={() => deliveries.refetch()} />
      ) : (
        <div className={tableWrap} aria-busy={deliveries.isFetching}>
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-b bg-muted/50">
              <tr>
                <th className={th}>Order</th>
                <th className={th}>Paid</th>
                <th className={th}>Deliver to</th>
                <th className={th}>Rider</th>
                <th className={th}>Status</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {deliveries.isLoading &&
                Array.from({ length: 5 }, (_, i) => (
                  <tr key={i}>
                    <td colSpan={5} className="p-3">
                      <Skeleton className="h-6 w-full" />
                    </td>
                  </tr>
                ))}
              {deliveries.data?.results.length === 0 && <EmptyRow colSpan={5}>No deliveries match these filters.</EmptyRow>}
              {deliveries.data?.results.map((d) => (
                <tr
                  key={d.id}
                  data-testid="delivery-row"
                  className={cn("hover:bg-muted/40", d.attention && "bg-amber-50 dark:bg-amber-950/30")}
                >
                  <td className={td}>
                    <Link href={`/admin/deliveries/${d.id}`} className="font-medium text-primary hover:underline">
                      {d.order.number}
                    </Link>
                    {d.attempt > 1 && <span className="ml-2 text-xs text-muted-foreground">attempt {d.attempt}</span>}
                  </td>
                  <td className={`${td} whitespace-nowrap text-muted-foreground`}>
                    {d.order.paid_at ? formatDateTime(d.order.paid_at, "en") : "—"}
                  </td>
                  <td className={td}>
                    <span className="block">{d.order.region}</span>
                    <span className="block text-xs text-muted-foreground">
                      {d.order.street} · {d.order.contact_name} · {plural(d.order.item_count, "item")}
                    </span>
                  </td>
                  <td className={td}>{d.rider ? d.rider.name : <span className="text-muted-foreground">—</span>}</td>
                  <td className={td}>
                    <span className="flex items-center gap-2">
                      <DeliveryBadge status={d.status} />
                      {d.attention && (
                        <AlertTriangle className="size-4 text-amber-600" aria-label="Needs attention" />
                      )}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {deliveries.data && (
        <Pagination
          count={deliveries.data.count}
          page={page}
          params={Object.fromEntries([...raw.entries()].filter(([k]) => k !== "page"))}
          pathname="/admin/deliveries"
          labels={{ previous: "Previous", next: "Next", page: "Page {page} of {pages}" }}
        />
      )}
    </>
  );
}
