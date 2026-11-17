"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { FormError } from "@/components/admin/ui";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/errors";
import type { DeliveryDetail } from "@/lib/api/types";
import { DELIVERY_ERRORS } from "@/lib/delivery-status";
import { useCandidates, useDeliveryActions } from "@/lib/queries/delivery";
import { cn } from "@/lib/utils";

export function errorMessage(err: unknown, fallback: string) {
  if (err instanceof ApiError) return (err.code && DELIVERY_ERRORS[err.code]) || err.detail || fallback;
  return fallback;
}

/** FR-007: region riders first, then the least busy; unavailable riders are shown but can't be picked. */
export function AssignDialog({
  delivery,
  open,
  onOpenChange,
}: {
  delivery: DeliveryDetail;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const candidates = useCandidates(delivery.id, open);
  const actions = useDeliveryActions(delivery.id);
  const [choice, setChoice] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const reassign = delivery.status === "assigned";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (choice == null) {
      setError("Choose a rider.");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      const updated = await actions.assign(choice, delivery.status, delivery.rider?.id ?? null);
      toast.success(`Assigned to ${updated.rider?.name ?? "the rider"}. They get the job on WhatsApp.`);
      onOpenChange(false);
    } catch (err) {
      setError(errorMessage(err, "Could not assign the rider. Try again."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{reassign ? "Reassign delivery" : "Assign a rider"}</DialogTitle>
          <DialogDescription>
            Order {delivery.order.number} to {delivery.order.region}.{" "}
            {reassign && delivery.rider ? `${delivery.rider.name} will be told the job was removed.` : ""}
          </DialogDescription>
        </DialogHeader>
        <form noValidate onSubmit={submit} className="flex flex-col gap-4" aria-busy={saving}>
          <fieldset className="flex max-h-80 flex-col gap-2 overflow-y-auto" aria-label="Riders">
            {candidates.isLoading && <Skeleton className="h-24 w-full" />}
            {candidates.data?.length === 0 && (
              <p className="text-sm text-muted-foreground">No active riders yet. Add riders first.</p>
            )}
            {candidates.data?.map((c) => {
              const current = c.id === delivery.rider?.id;
              const disabled = !c.is_available || current;
              return (
                <label
                  key={c.id}
                  className={cn(
                    "flex cursor-pointer items-start gap-3 rounded-md border p-3 text-sm",
                    choice === c.id && "border-primary bg-primary/5",
                    disabled && "cursor-not-allowed opacity-60",
                  )}
                >
                  <input
                    type="radio"
                    name="rider"
                    value={c.id}
                    disabled={disabled}
                    checked={choice === c.id}
                    onChange={() => setChoice(c.id)}
                    className="mt-1"
                  />
                  <span className="flex flex-1 flex-col gap-0.5">
                    <span className="font-medium">
                      {c.name}
                      {current && <span className="ml-2 text-xs text-muted-foreground">(current)</span>}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {c.vehicle} · {c.phone} · {c.regions.join(", ") || "no regions"}
                    </span>
                    <span className="flex flex-wrap gap-2 text-xs">
                      {c.covers_region && <span className="text-emerald-700">covers {delivery.order.region}</span>}
                      <span>{c.open_jobs} open {c.open_jobs === 1 ? "job" : "jobs"}</span>
                      {!c.is_available && <span className="text-amber-700">unavailable</span>}
                    </span>
                  </span>
                </label>
              );
            })}
          </fieldset>
          <FormError message={error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving || choice == null}>
              {saving && <Loader2 className="size-4 animate-spin" />}
              {reassign ? "Reassign" : "Assign"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
