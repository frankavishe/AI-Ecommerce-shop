"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, PackageSearch } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { describedBy, Field, inputClass } from "@/components/shop/form-field";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n/client";
import type { Dictionary } from "@/i18n/config";
import { bff } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Order } from "@/lib/api/types";
import { rememberGuestOrder } from "@/lib/guest-orders";
import { stripPhone, TZ_PHONE } from "@/lib/phone";
import { orderKey } from "@/lib/queries/orders";
import { cn } from "@/lib/utils";

function schema(t: Dictionary) {
  return z.object({
    number: z
      .string()
      .trim()
      .min(1, t.checkout.required)
      .transform((v) => v.toUpperCase()),
    phone: z
      .string()
      .transform(stripPhone)
      .refine((v) => TZ_PHONE.test(v), t.checkout.invalidPhone),
  });
}
type Values = z.input<ReturnType<typeof schema>>;
type Parsed = z.output<ReturnType<typeof schema>>;

export function TrackForm({ initialNumber }: { initialNumber: string }) {
  const { t } = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const resolver = useMemo(() => zodResolver(schema(t)), [t]);
  const { register, handleSubmit, formState } = useForm<Values, unknown, Parsed>({
    resolver,
    defaultValues: { number: initialNumber, phone: "" },
  });
  const errors = formState.errors;

  const onSubmit = handleSubmit(async ({ number, phone }) => {
    setFormError(null);
    try {
      const order = await bff<Order>("orders/lookup/", { method: "POST", json: { number, phone } });
      rememberGuestOrder(order.number, phone);
      qc.setQueryData(orderKey(order.number), order);
      router.push(`/orders/${order.number}`);
    } catch (e) {
      // Same message for a wrong number or a wrong phone, so neither can be probed (FR-016).
      setFormError(e instanceof ApiError && [400, 404].includes(e.status) ? t.track.notFound : t.common.errorBody);
    }
  });

  return (
    <div className="mx-auto w-full max-w-sm py-6">
      <PackageSearch className="mb-3 size-8 text-primary" aria-hidden />
      <h1 className="text-2xl font-semibold">{t.track.title}</h1>
      <p className="mb-6 mt-1 text-sm text-muted-foreground">{t.track.body}</p>
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4" aria-busy={formState.isSubmitting}>
        <Field id="number" label={t.track.number} error={errors.number?.message}>
          <input
            id="number"
            autoCapitalize="characters"
            autoComplete="off"
            className={cn(inputClass, "uppercase")}
            aria-invalid={!!errors.number}
            aria-describedby={describedBy("number", !!errors.number)}
            {...register("number")}
          />
        </Field>
        <Field id="phone" label={t.track.phone} hint={t.checkout.phoneHint} error={errors.phone?.message}>
          <input
            id="phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            className={inputClass}
            aria-invalid={!!errors.phone}
            aria-describedby={describedBy("phone", !!errors.phone, true)}
            {...register("phone")}
          />
        </Field>
        {formError && (
          <p role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
            {formError}
          </p>
        )}
        <Button type="submit" size="lg" disabled={formState.isSubmitting}>
          {formState.isSubmitting && <Loader2 className="size-4 animate-spin" />}
          {t.track.submit}
        </Button>
      </form>
    </div>
  );
}
