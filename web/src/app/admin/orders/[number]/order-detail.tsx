"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ErrorState, FormError, PageHeader, StatusBadge, statusLabel, tableWrap, td, th } from "@/components/admin/ui";
import { Field, inputClass } from "@/components/shop/form-field";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { bff } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { AdminOrder, OrderStatus } from "@/lib/api/types";
import { formatDateTime } from "@/lib/dates";
import { formatTZS } from "@/lib/money";
import { NEXT_STATUSES, ORDER_STATUSES } from "@/lib/order-status";
import { adminKeys, useAdminOrder } from "@/lib/queries/admin";

function StatusDialog({ order, open, onOpenChange }: { order: AdminOrder; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const suggested = NEXT_STATUSES[order.status];
  const others = ORDER_STATUSES.filter((s) => s !== order.status && !suggested.includes(s));
  const [status, setStatus] = useState<OrderStatus | "">(suggested[0] ?? "");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!status) {
      setError("Choose the new status.");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      const updated = await bff<AdminOrder>(`admin/orders/${order.number}/status/`, {
        method: "POST",
        json: { status, note: note.trim() },
      });
      qc.setQueryData(adminKeys.order(order.number), updated);
      qc.invalidateQueries({ queryKey: ["admin", "orders"] });
      qc.invalidateQueries({ queryKey: ["admin", "count"] });
      toast.success(`Order moved to ${statusLabel(status)}`);
      onOpenChange(false);
    } catch (err) {
      setError((err instanceof ApiError && err.detail) || "Could not change the status. Try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Change status</DialogTitle>
          <DialogDescription>
            Currently {statusLabel(order.status)}. The customer sees the new status on their order page.
          </DialogDescription>
        </DialogHeader>
        <form noValidate onSubmit={submit} className="flex flex-col gap-4" aria-busy={saving}>
          <Field id="new-status" label="New status">
            <select id="new-status" className={inputClass} value={status} onChange={(e) => setStatus(e.target.value as OrderStatus)}>
              <option value="">Choose…</option>
              {suggested.length > 0 && (
                <optgroup label="Next steps">
                  {suggested.map((s) => (
                    <option key={s} value={s}>
                      {statusLabel(s)}
                    </option>
                  ))}
                </optgroup>
              )}
              <optgroup label="Other">
                {others.map((s) => (
                  <option key={s} value={s}>
                    {statusLabel(s)}
                  </option>
                ))}
              </optgroup>
            </select>
          </Field>
          <Field id="status-note" label="Note" optional="optional" hint="Kept in the order history.">
            <textarea
              id="status-note"
              rows={3}
              maxLength={500}
              aria-describedby="status-note-hint"
              className={`${inputClass} h-auto py-2`}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </Field>
          <FormError message={error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving && <Loader2 className="size-4 animate-spin" />}
              Update status
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-xl border bg-card p-5">
      <h2 className="font-semibold">{title}</h2>
      {children}
    </section>
  );
}

export function AdminOrderDetail({ number }: { number: string }) {
  const order = useAdminOrder(number);
  const [open, setOpen] = useState(false);
  const [dialogKey, setDialogKey] = useState(0);
  const back = (
    <Link href="/admin/orders" className="text-sm text-muted-foreground hover:text-foreground">
      ← Orders
    </Link>
  );

  if (order.isLoading) return <PanelSkeleton />;
  if (order.error instanceof ApiError && order.error.status === 404) {
    return (
      <>
        {back}
        <PageHeader title="Order not found" />
      </>
    );
  }
  if (order.isError || !order.data) return <ErrorState onRetry={() => order.refetch()} />;

  const o = order.data;
  const events = [...o.events].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const final = NEXT_STATUSES[o.status].length === 0;

  return (
    <>
      {back}
      <PageHeader
        title={`Order ${o.number}`}
        description={`Placed ${formatDateTime(o.placed_at, "en")}${o.paid_at ? ` · paid ${formatDateTime(o.paid_at, "en")}` : ""}`}
        actions={
          <>
            <StatusBadge status={o.status} testId="admin-order-status" />
            <Button
              variant={final ? "outline" : "default"}
              onClick={() => {
                setDialogKey((k) => k + 1);
                setOpen(true);
              }}
            >
              Change status
            </Button>
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="flex flex-col gap-6">
          <Panel title="Items">
            <div className={tableWrap}>
              <table className="w-full text-sm">
                <thead className="border-b bg-muted/50">
                  <tr>
                    <th className={th}>Product</th>
                    <th className={`${th} text-right`}>Unit</th>
                    <th className={`${th} text-right`}>Qty</th>
                    <th className={`${th} text-right`}>Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {o.items.map((item, i) => (
                    <tr key={`${item.product}-${i}`}>
                      <td className={td}>{item.product_name}</td>
                      <td className={`${td} text-right tabular-nums`}>{formatTZS(item.unit_price)}</td>
                      <td className={`${td} text-right tabular-nums`}>{item.quantity}</td>
                      <td className={`${td} text-right tabular-nums`}>{formatTZS(item.line_total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <dl className="ml-auto flex w-full max-w-xs flex-col gap-1 text-sm">
              <div className="flex justify-between">
                <dt>Subtotal</dt>
                <dd className="tabular-nums">{formatTZS(o.subtotal)}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Delivery</dt>
                <dd className="tabular-nums">{formatTZS(o.delivery_fee)}</dd>
              </div>
              <div className="flex justify-between border-t pt-1 font-semibold">
                <dt>Total</dt>
                <dd className="tabular-nums">{formatTZS(o.total)}</dd>
              </div>
            </dl>
          </Panel>

          <Panel title="Payments">
            {o.payments.length === 0 ? (
              <p className="text-sm text-muted-foreground">No payment attempts yet.</p>
            ) : (
              <div className={tableWrap}>
                <table className="w-full min-w-[560px] text-sm">
                  <thead className="border-b bg-muted/50">
                    <tr>
                      <th className={th}>Reference</th>
                      <th className={th}>Method</th>
                      <th className={th}>Status</th>
                      <th className={th}>Receipt</th>
                      <th className={`${th} text-right`}>Amount</th>
                      <th className={th}>Updated</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {o.payments.map((p) => (
                      <tr key={p.reference}>
                        <td className={`${td} font-mono text-xs`}>{p.reference}</td>
                        <td className={td}>
                          {p.method === "card" ? "Card" : "Mobile money"}
                          {p.channel && <span className="block text-xs text-muted-foreground">{p.channel}</span>}
                        </td>
                        <td className={`${td} capitalize`}>{p.status?.replace(/_/g, " ") ?? "—"}</td>
                        <td className={`${td} font-mono text-xs`}>{p.receipt || "—"}</td>
                        <td className={`${td} text-right tabular-nums`}>
                          {formatTZS(p.amount)}
                          {p.collected_amount && p.collected_amount !== p.amount && (
                            <span className="block text-xs text-amber-700">collected {formatTZS(p.collected_amount)}</span>
                          )}
                        </td>
                        <td className={`${td} whitespace-nowrap text-muted-foreground`}>{formatDateTime(p.updated_at, "en")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </div>

        <div className="flex flex-col gap-6">
          <Panel title="Customer">
            <dl className="flex flex-col gap-2 text-sm">
              <div>
                <dt className="text-muted-foreground">Name</dt>
                <dd>{o.contact_name}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Phone</dt>
                <dd>
                  <a href={`tel:${o.contact_phone}`} className="hover:underline">
                    {o.contact_phone}
                  </a>
                </dd>
              </div>
              {o.contact_email && (
                <div>
                  <dt className="text-muted-foreground">Email</dt>
                  <dd className="break-all">{o.contact_email}</dd>
                </div>
              )}
              <div>
                <dt className="text-muted-foreground">Account</dt>
                <dd>{o.user || "Guest"}</dd>
              </div>
            </dl>
          </Panel>
          <Panel title="Delivery">
            <p className="text-sm">{[o.street, o.district, o.region].filter(Boolean).join(", ")}</p>
            {o.notes && <p className="rounded-md bg-muted p-2 text-sm">“{o.notes}”</p>}
          </Panel>
          <Panel title="History">
            <ol className="flex flex-col gap-3">
              {events.map((e, i) => (
                <li key={`${e.created_at}-${i}`} className="flex flex-col gap-1 border-l-2 pl-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={e.status} />
                    <span className="text-xs text-muted-foreground">{formatDateTime(e.created_at, "en")}</span>
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {e.source}
                    {e.actor ? ` · ${e.actor}` : ""}
                  </span>
                  {e.note && <p>{e.note}</p>}
                </li>
              ))}
            </ol>
          </Panel>
        </div>
      </div>

      <StatusDialog key={dialogKey} order={o} open={open} onOpenChange={setOpen} />
    </>
  );
}
