"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, MapPin, Pencil, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { describedBy, Field, inputClass } from "@/components/shop/form-field";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useT } from "@/i18n/client";
import type { Dictionary } from "@/i18n/config";
import { bff } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { applyServerErrors } from "@/lib/forms";
import type { Address, DeliveryRegions, Paginated } from "@/lib/api/types";
import { formatTZS } from "@/lib/money";

/** Shared with the checkout saved-address picker. */
const addressesKey = ["addresses"] as const;

function schema(t: Dictionary) {
  const required = (max: number) => z.string().trim().min(1, t.checkout.required).max(max);
  return z.object({
    label: z.string().trim().max(50),
    region: required(80),
    district: z.string().trim().max(80),
    street: required(255),
    is_default: z.boolean(),
  });
}
type Values = z.infer<ReturnType<typeof schema>>;

function AddressDialog({
  address,
  open,
  onOpenChange,
}: {
  address: Address | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useT();
  const qc = useQueryClient();
  const regions = useQuery({ queryKey: ["delivery-regions"], queryFn: () => bff<DeliveryRegions>("delivery-regions/") });
  const [formError, setFormError] = useState<string | null>(null);
  const resolver = useMemo(() => zodResolver(schema(t)), [t]);
  const { register, handleSubmit, formState, setError, getValues } = useForm<Values>({
    resolver,
    defaultValues: {
      label: address?.label ?? "",
      region: address?.region ?? "",
      district: address?.district ?? "",
      street: address?.street ?? "",
      is_default: address?.is_default ?? false,
    },
  });
  const errors = formState.errors;

  const onSubmit = handleSubmit(async (v) => {
    setFormError(null);
    try {
      await bff<Address>(address ? `auth/addresses/${address.id}/` : "auth/addresses/", {
        method: address ? "PATCH" : "POST",
        json: v,
      });
      await qc.invalidateQueries({ queryKey: addressesKey });
      toast.success(t.account.addressSaved);
      onOpenChange(false);
    } catch (e) {
      setFormError(applyServerErrors(e, { getValues, setError }, t.common.errorBody));
    }
  });

  // A region that was renamed or retired since the address was saved stays selectable.
  const names = regions.data?.regions.map((r) => r.name) ?? [];
  const extra = address?.region && !names.includes(address.region) ? [address.region] : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{address ? t.account.editAddress : t.account.addAddress}</DialogTitle>
        </DialogHeader>
        {regions.isLoading ? (
          // Options must exist before the saved region is applied to the <select>.
          <Skeleton className="h-64 w-full" />
        ) : (
          <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4" aria-busy={formState.isSubmitting}>
            <Field id="label" label={t.account.label} hint={t.account.labelHint} optional={t.common.optional}>
              <input id="label" className={inputClass} aria-describedby={describedBy("label", false, true)} {...register("label")} />
            </Field>
            <Field id="region" label={t.checkout.region} error={errors.region?.message}>
              <select
                id="region"
                className={inputClass}
                aria-invalid={!!errors.region}
                aria-describedby={describedBy("region", !!errors.region)}
                {...register("region")}
              >
                <option value="">{t.checkout.chooseRegion}</option>
                {extra.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
                {regions.data?.regions.map((r) => (
                  <option key={r.name} value={r.name}>
                    {r.name} · {formatTZS(r.fee)}
                  </option>
                ))}
              </select>
            </Field>
            <Field id="district" label={t.checkout.district} optional={t.common.optional}>
              <input id="district" autoComplete="address-level2" className={inputClass} {...register("district")} />
            </Field>
            <Field id="street" label={t.checkout.street} error={errors.street?.message}>
              <input
                id="street"
                autoComplete="street-address"
                className={inputClass}
                aria-invalid={!!errors.street}
                aria-describedby={describedBy("street", !!errors.street)}
                {...register("street")}
              />
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="size-4 accent-primary" {...register("is_default")} />
              {t.account.makeDefault}
            </label>
            {formError && (
              <p role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {formError}
              </p>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                {t.common.cancel}
              </Button>
              <Button type="submit" disabled={formState.isSubmitting}>
                {formState.isSubmitting && <Loader2 className="size-4 animate-spin" />}
                {t.common.save}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function AddressCard({ address, onEdit }: { address: Address; onEdit: () => void }) {
  const { t } = useT();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const remove = useMutation({
    mutationFn: () => bff<null>(`auth/addresses/${address.id}/`, { method: "DELETE" }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: addressesKey });
      toast.success(t.account.addressDeleted);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.detail : t.common.errorBody),
  });

  return (
    <li className="flex flex-col gap-3 rounded-xl border p-4">
      <div className="flex items-start gap-3">
        <MapPin className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 font-medium">
            {address.label || address.region}
            {address.is_default && <Badge variant="secondary">{t.account.default}</Badge>}
          </p>
          <p className="text-sm text-muted-foreground">
            {[address.street, address.district, address.region].filter(Boolean).join(", ")}
          </p>
        </div>
      </div>
      {confirming ? (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span>{t.account.deleteConfirm}</span>
          <Button size="sm" variant="destructive" onClick={() => remove.mutate()} disabled={remove.isPending}>
            {remove.isPending && <Loader2 className="size-4 animate-spin" />}
            {t.account.yesDelete}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
            {t.common.cancel}
          </Button>
        </div>
      ) : (
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={onEdit}>
            <Pencil className="size-4" />
            {t.common.edit}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setConfirming(true)}>
            <Trash2 className="size-4" />
            {t.common.delete}
          </Button>
        </div>
      )}
    </li>
  );
}

export function AddressBook() {
  const { t } = useT();
  const addresses = useQuery({ queryKey: addressesKey, queryFn: () => bff<Paginated<Address>>("auth/addresses/") });
  const [editing, setEditing] = useState<Address | null>(null);
  const [open, setOpen] = useState(false);
  // Remounts the dialog form each time it opens so it starts from the chosen address.
  const [formKey, setFormKey] = useState(0);

  const openFor = (address: Address | null) => {
    setEditing(address);
    setFormKey((k) => k + 1);
    setOpen(true);
  };

  if (addresses.isLoading) return <PanelSkeleton />;
  if (addresses.isError) {
    return (
      <div className="flex flex-col items-start gap-3">
        <p>{t.common.errorBody}</p>
        <Button variant="outline" onClick={() => addresses.refetch()}>
          {t.common.retry}
        </Button>
      </div>
    );
  }
  const list = addresses.data?.results ?? [];

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">{t.account.addresses}</h2>
        <Button size="sm" onClick={() => openFor(null)}>
          <Plus className="size-4" />
          {t.account.addAddress}
        </Button>
      </div>
      {list.length === 0 ? (
        <p className="rounded-xl border border-dashed p-6 text-center text-muted-foreground">{t.account.noAddresses}</p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {list.map((a) => (
            <AddressCard key={a.id} address={a} onEdit={() => openFor(a)} />
          ))}
        </ul>
      )}
      <AddressDialog key={formKey} address={editing} open={open} onOpenChange={setOpen} />
    </section>
  );
}
