"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { ErrorState, FormError, PageHeader, plural } from "@/components/admin/ui";
import { Field, inputClass } from "@/components/shop/form-field";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ApiError } from "@/lib/api/errors";
import type { DeliveryDetail } from "@/lib/api/types";
import { formatDateTime } from "@/lib/dates";
import { canAssign, canUnassign, DELIVERY_LABELS, OVERRIDES } from "@/lib/delivery-status";
import { formatTZS } from "@/lib/money";
import { useDelivery, useDeliveryActions } from "@/lib/queries/delivery";
import { cn } from "@/lib/utils";
import { DeliveryBadge } from "../delivery-badge";
import { AssignDialog, errorMessage } from "./assign-dialog";

type Override = "picked_up" | "on_the_way" | "delivered" | "failed";

function StatusDialog({ delivery, open, onOpenChange }: { delivery: DeliveryDetail; open: boolean; onOpenChange: (o: boolean) => void }) {
  const choices = OVERRIDES[delivery.status] ?? [];
  const actions = useDeliveryActions(delivery.id);
  const [status, setStatus] = useState<Override | "">(choices[0] ?? "");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!status) return setError("Choose the new status.");
    if (status === "failed" && !note.trim()) return setError("Say why the delivery failed.");
    setError(null);
    setSaving(true);
    try {
      await actions.setStatus(status, note.trim(), delivery.status);
      toast.success(`Delivery marked ${DELIVERY_LABELS[status].toLowerCase()}`);
      onOpenChange(false);
    } catch (err) {
      setError(errorMessage(err, "Could not change the status. Try again."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Update on the rider&apos;s behalf</DialogTitle>
          <DialogDescription>
            Use this when the rider can&apos;t message the shop. The order status follows the delivery.
          </DialogDescription>
        </DialogHeader>
        <form noValidate onSubmit={submit} className="flex flex-col gap-4" aria-busy={saving}>
          <Field id="delivery-status" label="New status">
            <select id="delivery-status" className={inputClass} value={status} onChange={(e) => setStatus(e.target.value as Override)}>
              {choices.map((s) => (
                <option key={s} value={s}>
                  {DELIVERY_LABELS[s]}
                </option>
              ))}
            </select>
          </Field>
          <Field id="delivery-note" label="Note" optional={status === "failed" ? undefined : "optional"} hint="Kept in the delivery history; never shown to the customer.">
            <textarea
              id="delivery-note"
              rows={3}
              maxLength={255}
              aria-describedby="delivery-note-hint"
              className={cn(inputClass, "h-auto py-2")}
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
              Save
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

const NOTIFICATION_LABELS: Record<string, string> = {
  rider_assigned: "Job sent to rider",
  rider_removed: "Removal sent to rider",
  rider_cancelled: "Cancellation sent to rider",
  customer_failed: "“Couldn't deliver” sent to customer",
  rider_welcome: "Welcome sent to rider",
};

export function AdminDeliveryDetail({ id }: { id: number }) {
  const delivery = useDelivery(id);
  const actions = useDeliveryActions(id);
  const [dialog, setDialog] = useState<"assign" | "status" | null>(null);
  const [dialogKey, setDialogKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const back = (
    <Link href="/admin/deliveries" className="text-sm text-muted-foreground hover:text-foreground">
      ← Deliveries
    </Link>
  );

  if (delivery.isLoading) return <PanelSkeleton />;
  if (delivery.error instanceof ApiError && delivery.error.status === 404) {
    return (
      <>
        {back}
        <PageHeader title="Delivery not found" />
      </>
    );
  }
  if (delivery.isError || !delivery.data) return <ErrorState onRetry={() => delivery.refetch()} />;

  const d = delivery.data;
  const open = (which: "assign" | "status") => {
    setDialogKey((k) => k + 1);
    setDialog(which);
  };
  const unassign = async () => {
    setBusy(true);
    try {
      await actions.unassign(d.rider?.id ?? null);
      toast.success("Rider removed. The delivery is waiting again.");
    } catch (err) {
      toast.error(errorMessage(err, "Could not unassign. Try again."));
    } finally {
      setBusy(false);
    }
  };
  const events = [...d.events].reverse();

  return (
    <>
      {back}
      <PageHeader
        title={`Delivery for ${d.order.number}`}
        description={`Attempt ${d.attempt} · created ${formatDateTime(d.created_at, "en")}`}
        actions={
          <>
            <DeliveryBadge status={d.status} testId="delivery-status" />
            {canAssign(d.status) && (
              <Button onClick={() => open("assign")}>{d.status === "assigned" ? "Reassign" : "Assign rider"}</Button>
            )}
            {canUnassign(d.status) && (
              <Button variant="outline" onClick={unassign} disabled={busy}>
                {busy && <Loader2 className="size-4 animate-spin" />}
                Unassign
              </Button>
            )}
            {OVERRIDES[d.status] && (
              <Button variant="outline" onClick={() => open("status")}>
                Update status
              </Button>
            )}
          </>
        }
      />

      {d.attention && (
        <p role="status" className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <AlertTriangle className="size-4" aria-hidden />
          {d.status === "failed"
            ? `Delivery failed${d.failure_reason ? `: “${d.failure_reason}”` : ""}. Try again or cancel the order.`
            : "This delivery has been waiting for a rider for a while."}
        </p>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex flex-col gap-6">
          <Panel title="Order">
            <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">Order</dt>
                <dd>
                  <Link href={`/admin/orders/${d.order.number}`} className="font-medium text-primary hover:underline">
                    {d.order.number}
                  </Link>
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Deliver to</dt>
                <dd>
                  {d.order.street}, {d.order.region}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Customer</dt>
                <dd>{d.order.contact_name}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Items · total paid</dt>
                <dd>
                  {plural(d.order.item_count, "item")} · {formatTZS(d.order.total)}
                </dd>
              </div>
            </dl>
          </Panel>
          <Panel title="History">
            <ol className="flex flex-col gap-3" data-testid="delivery-history">
              {events.map((e, i) => (
                <li key={`${e.created_at}-${i}`} className="flex flex-col gap-1 border-l-2 pl-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <DeliveryBadge status={e.status} />
                    <span className="text-xs text-muted-foreground">{formatDateTime(e.created_at, "en")}</span>
                    {e.attempt > 1 && <span className="text-xs text-muted-foreground">attempt {e.attempt}</span>}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {e.actor_type}
                    {e.actor_name ? ` · ${e.actor_name}` : ""}
                    {e.rider && e.status !== "waiting" ? ` · rider ${e.rider}` : ""}
                  </span>
                  {e.note && <p>{e.note}</p>}
                </li>
              ))}
              {events.length === 0 && <li className="text-sm text-muted-foreground">Waiting for a rider since payment.</li>}
            </ol>
          </Panel>
        </div>

        <div className="flex flex-col gap-6">
          <Panel title="Rider">
            {d.rider ? (
              <dl className="flex flex-col gap-2 text-sm">
                <div>
                  <dt className="text-muted-foreground">Name</dt>
                  <dd data-testid="delivery-rider">{d.rider.name}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Phone</dt>
                  <dd>
                    <a href={`tel:${d.rider.phone}`} className="hover:underline">
                      {d.rider.phone}
                    </a>
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Vehicle</dt>
                  <dd className="capitalize">{d.rider.vehicle ?? "—"}</dd>
                </div>
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">No rider assigned.</p>
            )}
          </Panel>
          <Panel title="Messages">
            {d.notifications.length === 0 ? (
              <p className="text-sm text-muted-foreground">No messages sent yet.</p>
            ) : (
              <ul className="flex flex-col gap-2 text-sm">
                {d.notifications.map((n, i) => (
                  <li key={i} className="flex flex-col">
                    <span>{NOTIFICATION_LABELS[n.kind] ?? n.kind}</span>
                    <span className={cn("text-xs", n.outbound_status === "failed" ? "text-destructive" : "text-muted-foreground")}>
                      {n.outbound_status ?? n.state} · {formatDateTime(n.created_at, "en")}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>

      <AssignDialog key={`a${dialogKey}`} delivery={d} open={dialog === "assign"} onOpenChange={(o) => setDialog(o ? "assign" : null)} />
      {OVERRIDES[d.status] && (
        <StatusDialog key={`s${dialogKey}`} delivery={d} open={dialog === "status"} onOpenChange={(o) => setDialog(o ? "status" : null)} />
      )}
    </>
  );
}
