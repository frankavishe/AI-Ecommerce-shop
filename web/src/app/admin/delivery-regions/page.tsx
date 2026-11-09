"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { EmptyRow, ErrorState, FormError, PageHeader, tableWrap, td, th } from "@/components/admin/ui";
import { describedBy, Field, inputClass } from "@/components/shop/form-field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { bff } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { AdminDeliveryRegion } from "@/lib/api/types";
import { applyServerErrors } from "@/lib/forms";
import { formatTZS, isMoney } from "@/lib/money";
import { adminKeys, useAdminRegions } from "@/lib/queries/admin";

const schema = z.object({
  name: z.string().trim().min(1, "Name is required.").max(80),
  fee: z.string().trim().refine(isMoney, "Enter a fee like 3000 (0 for free delivery)."),
  is_active: z.boolean(),
});
type Values = z.infer<typeof schema>;

function RegionDialog({
  region,
  open,
  onOpenChange,
}: {
  region: AdminDeliveryRegion | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const qc = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: region?.name ?? "",
      fee: region?.fee.replace(/\.00$/, "") ?? "",
      is_active: region?.is_active ?? true,
    },
  });
  const { register, handleSubmit, formState } = form;
  const errors = formState.errors;

  const onSubmit = handleSubmit(async (v) => {
    setFormError(null);
    try {
      await bff<AdminDeliveryRegion>(region ? `admin/delivery-regions/${region.id}/` : "admin/delivery-regions/", {
        method: region ? "PATCH" : "POST",
        json: v,
      });
      await qc.invalidateQueries({ queryKey: adminKeys.regions });
      qc.invalidateQueries({ queryKey: ["delivery-regions"] });
      toast.success("Region saved");
      onOpenChange(false);
    } catch (e) {
      setFormError(applyServerErrors(e, form, "Could not save the region. Try again."));
    }
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{region ? "Edit region" : "New delivery region"}</DialogTitle>
        </DialogHeader>
        <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4" aria-busy={formState.isSubmitting}>
          <Field id="region-name" label="Name" error={errors.name?.message}>
            <input id="region-name" className={inputClass} aria-invalid={!!errors.name} aria-describedby={describedBy("region-name", !!errors.name)} {...register("name")} />
          </Field>
          <Field id="region-fee" label="Fee (TSh)" error={errors.fee?.message}>
            <input id="region-fee" inputMode="decimal" className={inputClass} aria-invalid={!!errors.fee} aria-describedby={describedBy("region-fee", !!errors.fee)} {...register("fee")} />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-primary" {...register("is_active")} />
            Offered at checkout
          </label>
          <FormError message={formError} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={formState.isSubmitting}>
              {formState.isSubmitting && <Loader2 className="size-4 animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DeleteButton({ region }: { region: AdminDeliveryRegion }) {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const remove = useMutation({
    mutationFn: () => bff<null>(`admin/delivery-regions/${region.id}/`, { method: "DELETE" }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: adminKeys.regions });
      toast.success("Region deleted");
    },
    onError: (e) => {
      setConfirming(false);
      toast.error((e instanceof ApiError && e.detail) || "Could not delete the region.");
    },
  });
  if (!confirming) {
    return (
      <Button variant="ghost" size="icon" aria-label={`Delete ${region.name}`} onClick={() => setConfirming(true)}>
        <Trash2 className="size-4" />
      </Button>
    );
  }
  return (
    <span className="inline-flex gap-1">
      <Button variant="destructive" size="sm" onClick={() => remove.mutate()} disabled={remove.isPending}>
        {remove.isPending && <Loader2 className="size-4 animate-spin" />}
        Delete
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
        Keep
      </Button>
    </span>
  );
}

export default function AdminRegionsPage() {
  const regions = useAdminRegions();
  const [editing, setEditing] = useState<AdminDeliveryRegion | null>(null);
  const [open, setOpen] = useState(false);
  const [formKey, setFormKey] = useState(0);

  const openFor = (r: AdminDeliveryRegion | null) => {
    setEditing(r);
    setFormKey((k) => k + 1);
    setOpen(true);
  };

  return (
    <>
      <PageHeader
        title="Delivery regions"
        description="Regions and fees offered at checkout. Unlisted regions use the default fee."
        actions={
          <Button onClick={() => openFor(null)}>
            <Plus className="size-4" />
            Add region
          </Button>
        }
      />
      {regions.isError ? (
        <ErrorState onRetry={() => regions.refetch()} />
      ) : (
        <div className={tableWrap}>
          <table className="w-full min-w-[440px] text-sm">
            <thead className="border-b bg-muted/50">
              <tr>
                <th className={th}>Region</th>
                <th className={`${th} text-right`}>Fee</th>
                <th className={th}>Status</th>
                <th className={`${th} text-right`}>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {regions.isLoading && (
                <tr>
                  <td colSpan={4} className="p-3">
                    <Skeleton className="h-8 w-full" />
                  </td>
                </tr>
              )}
              {regions.data?.length === 0 && <EmptyRow colSpan={4}>No regions yet.</EmptyRow>}
              {regions.data?.map((r) => (
                <tr key={r.id}>
                  <td className={`${td} font-medium`}>{r.name}</td>
                  <td className={`${td} text-right tabular-nums`}>{formatTZS(r.fee)}</td>
                  <td className={td}>
                    {r.is_active === false ? <Badge variant="outline">Off</Badge> : <Badge variant="secondary">Offered</Badge>}
                  </td>
                  <td className={`${td} whitespace-nowrap text-right`}>
                    <Button variant="ghost" size="icon" aria-label={`Edit ${r.name}`} onClick={() => openFor(r)}>
                      <Pencil className="size-4" />
                    </Button>
                    <DeleteButton region={r} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <RegionDialog key={formKey} region={editing} open={open} onOpenChange={setOpen} />
    </>
  );
}
