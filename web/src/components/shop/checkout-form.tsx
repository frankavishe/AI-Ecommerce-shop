"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CreditCard, Loader2, Smartphone } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { Field, inputClass as input } from "@/components/shop/form-field";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n/client";
import type { Dictionary } from "@/i18n/config";
import { bff } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Address, DeliveryRegions, Paginated, PlacedOrder } from "@/lib/api/types";
import { rememberGuestOrder, setLastOrder } from "@/lib/guest-orders";
import { addMoney, formatTZS } from "@/lib/money";
import { stripPhone, TZ_PHONE } from "@/lib/phone";
import { cartKey, useCart } from "@/lib/queries/cart";
import { useSession } from "@/lib/queries/session";
import { cn } from "@/lib/utils";

export const NETWORKS = [
  { value: "Mpesa", label: "M-Pesa (Vodacom)" },
  { value: "AirtelMoney", label: "Airtel Money" },
  { value: "TigoPesa", label: "Mixx by Yas (Tigo Pesa)" },
  { value: "HaloPesa", label: "HaloPesa" },
] as const;

const NEW_ADDRESS = "new";

function schema(t: Dictionary, savedAddress: boolean) {
  const required = (max: number) => z.string().trim().min(1, t.checkout.required).max(max);
  return z
    .object({
      contact_name: required(120),
      contact_phone: z
        .string()
        .transform(stripPhone)
        .refine((v) => TZ_PHONE.test(v), t.checkout.invalidPhone),
      email: z.string().trim().refine((v) => !v || z.email().safeParse(v).success, t.checkout.invalidEmail),
      region: savedAddress ? z.string() : required(80),
      district: z.string().trim().max(80),
      street: savedAddress ? z.string() : required(255),
      notes: z.string().trim(),
      payment_method: z.enum(["mobile_money", "card"]),
      network: z.string(),
    })
    .superRefine((v, ctx) => {
      if (v.payment_method === "card" && !v.email) {
        ctx.addIssue({ code: "custom", path: ["email"], message: t.checkout.emailForCard });
      }
    });
}
type Values = z.input<ReturnType<typeof schema>>;
type Parsed = z.output<ReturnType<typeof schema>>;

export function CheckoutForm() {
  const { t } = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const { data: cart, isLoading: cartLoading } = useCart();
  const { data: user, isLoading: userLoading } = useSession();
  const regions = useQuery({ queryKey: ["delivery-regions"], queryFn: () => bff<DeliveryRegions>("delivery-regions/") });
  const addresses = useQuery({
    queryKey: ["addresses"],
    queryFn: () => bff<Paginated<Address>>("auth/addresses/"),
    enabled: Boolean(user),
  });
  const saved = addresses.data?.results ?? [];
  const [addressChoice, setAddressId] = useState<string | null>(null);
  const defaultAddress = saved.find((a) => a.is_default) ?? saved[0];
  const addressId = addressChoice ?? (defaultAddress ? String(defaultAddress.id) : NEW_ADDRESS);
  const [formError, setFormError] = useState<string | null>(null);
  const [redirecting, setRedirecting] = useState(false);
  const [placed, setPlaced] = useState(false);

  const usingSaved = addressId !== NEW_ADDRESS;
  const resolver = useMemo(() => zodResolver(schema(t, usingSaved)), [t, usingSaved]);
  const form = useForm<Values, unknown, Parsed>({
    resolver,
    defaultValues: {
      contact_name: "",
      contact_phone: "",
      email: "",
      region: "",
      district: "",
      street: "",
      notes: "",
      payment_method: "mobile_money",
      network: "",
    },
  });
  const { register, handleSubmit, setError, formState, control, reset, getValues } = form;
  const errors = formState.errors;

  // Prefill contact details from the logged-in profile once.
  useEffect(() => {
    if (!user) return;
    const name = [user.first_name, user.last_name].filter(Boolean).join(" ");
    reset({ ...getValues(), contact_name: name || user.username, contact_phone: user.phone ?? "", email: user.email ?? "" });
  }, [user, reset, getValues]);

  const [method, region] = useWatch({ control, name: ["payment_method", "region"] });
  const regionName = usingSaved ? saved.find((a) => String(a.id) === addressId)?.region : region;
  const fee = regionName
    ? (regions.data?.regions.find((r) => r.name === regionName)?.fee ?? regions.data?.default_fee)
    : undefined;
  const total = cart && fee ? addMoney(cart.subtotal, fee) : null;

  useEffect(() => {
    if (!cartLoading && cart && cart.items.length === 0 && !placed) router.replace("/cart");
  }, [cart, cartLoading, placed, router]);

  if (cartLoading || userLoading || !cart) return <PanelSkeleton />;

  const onSubmit = async (v: Parsed) => {
    setFormError(null);
    const body: Record<string, unknown> = {
      contact_name: v.contact_name,
      contact_phone: v.contact_phone,
      payment_method: v.payment_method,
      notes: v.notes,
    };
    if (usingSaved) body.address_id = Number(addressId);
    else Object.assign(body, { region: v.region, district: v.district, street: v.street });
    if (v.email) body.email = v.email;
    if (v.payment_method === "mobile_money" && v.network) body.network = v.network;

    try {
      const order = await bff<PlacedOrder>("checkout/", { method: "POST", json: body });
      setPlaced(true);
      rememberGuestOrder(order.number, order.contact_phone);
      setLastOrder(order.number);
      if (order.payment_error) qc.setQueryData(["payment-error", order.number], order.payment_error);
      qc.setQueryData(cartKey, { items: [], item_count: 0, subtotal: "0.00" });
      if (order.payment_method === "card" && order.payment_url) {
        setRedirecting(true);
        window.location.assign(order.payment_url);
        return;
      }
      router.push(`/orders/${order.number}?pending=1`);
    } catch (error) {
      if (error instanceof ApiError) {
        let mapped = false;
        for (const [field, messages] of Object.entries(error.fields ?? {})) {
          if (field in getValues()) {
            setError(field as keyof Values, { message: messages[0] });
            mapped = true;
          }
        }
        if (!mapped) setFormError(error.detail);
        if (error.code === "out_of_stock" || error.code === "inactive_product" || error.code === "empty_cart") {
          qc.invalidateQueries({ queryKey: cartKey });
        }
      } else {
        setFormError(t.common.errorBody);
      }
    }
  };

  const describe = (name: keyof Values, hint?: boolean) =>
    errors[name] ? `${name}-error` : hint ? `${name}-hint` : undefined;

  return (
    <form
      noValidate
      onSubmit={handleSubmit(onSubmit)}
      className="grid gap-6 lg:grid-cols-[1fr_340px]"
      aria-busy={formState.isSubmitting}
    >
      <div className="flex flex-col gap-6">
        <h1 className="text-2xl font-semibold">{t.checkout.title}</h1>

        <fieldset className="flex flex-col gap-4 rounded-xl border p-4 sm:p-5">
          <legend className="px-1 font-semibold">{t.checkout.contact}</legend>
          <Field id="contact_name" label={t.checkout.name} error={errors.contact_name?.message}>
            <input id="contact_name" autoComplete="name" className={input} aria-invalid={!!errors.contact_name} aria-describedby={describe("contact_name")} {...register("contact_name")} />
          </Field>
          <Field id="contact_phone" label={t.checkout.phone} hint={t.checkout.phoneHint} error={errors.contact_phone?.message}>
            <input id="contact_phone" type="tel" inputMode="tel" autoComplete="tel" className={input} aria-invalid={!!errors.contact_phone} aria-describedby={describe("contact_phone", true)} {...register("contact_phone")} />
          </Field>
          <Field id="email" label={t.checkout.email} hint={t.checkout.emailHint} optional={method === "card" ? undefined : t.common.optional} error={errors.email?.message}>
            <input id="email" type="email" autoComplete="email" className={input} aria-invalid={!!errors.email} aria-describedby={describe("email", true)} {...register("email")} />
          </Field>
        </fieldset>

        <fieldset className="flex flex-col gap-4 rounded-xl border p-4 sm:p-5">
          <legend className="px-1 font-semibold">{t.checkout.delivery}</legend>
          {saved.length > 0 && (
            <Field id="address_id" label={t.checkout.savedAddress}>
              <select id="address_id" className={input} value={addressId} onChange={(e) => setAddressId(e.target.value)}>
                {saved.map((a) => (
                  <option key={a.id} value={a.id}>
                    {[a.label, a.street, a.district, a.region].filter(Boolean).join(", ")}
                  </option>
                ))}
                <option value={NEW_ADDRESS}>{t.checkout.newAddress}</option>
              </select>
            </Field>
          )}
          {!usingSaved && (
            <>
              <Field id="region" label={t.checkout.region} error={errors.region?.message}>
                <select id="region" className={input} aria-invalid={!!errors.region} aria-describedby={describe("region")} {...register("region")}>
                  <option value="">{t.checkout.chooseRegion}</option>
                  {regions.data?.regions.map((r) => (
                    <option key={r.name} value={r.name}>
                      {r.name} · {formatTZS(r.fee)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field id="district" label={t.checkout.district} optional={t.common.optional} error={errors.district?.message}>
                <input id="district" autoComplete="address-level2" className={input} {...register("district")} />
              </Field>
              <Field id="street" label={t.checkout.street} error={errors.street?.message}>
                <input id="street" autoComplete="street-address" className={input} aria-invalid={!!errors.street} aria-describedby={describe("street")} {...register("street")} />
              </Field>
            </>
          )}
          <Field id="notes" label={t.checkout.notes} optional={t.common.optional}>
            <textarea id="notes" rows={2} className={cn(input, "h-auto py-2")} {...register("notes")} />
          </Field>
        </fieldset>

        <fieldset className="flex flex-col gap-3 rounded-xl border p-4 sm:p-5">
          <legend className="px-1 font-semibold">{t.checkout.payment}</legend>
          {(
            [
              { value: "mobile_money", label: t.checkout.mobileMoney, hint: t.checkout.mobileMoneyHint, Icon: Smartphone },
              { value: "card", label: t.checkout.card, hint: t.checkout.cardHint, Icon: CreditCard },
            ] as const
          ).map(({ value, label, hint, Icon }) => (
            <div
              key={value}
              className={cn(
                "flex items-start gap-3 rounded-lg border p-3",
                method === value && "border-primary bg-accent",
              )}
            >
              <input
                id={`pay-${value}`}
                type="radio"
                value={value}
                aria-describedby={`pay-${value}-hint`}
                className="mt-1 size-4 accent-primary"
                {...register("payment_method")}
              />
              <div>
                <label htmlFor={`pay-${value}`} className="flex items-center gap-2 font-medium">
                  <Icon className="size-4" aria-hidden />
                  {label}
                </label>
                <p id={`pay-${value}-hint`} className="text-sm text-muted-foreground">
                  {hint}
                </p>
              </div>
            </div>
          ))}
          {method === "mobile_money" && (
            <Field id="network" label={t.checkout.network}>
              <select id="network" className={input} {...register("network")}>
                <option value="">{t.checkout.networkAuto}</option>
                {NETWORKS.map((n) => (
                  <option key={n.value} value={n.value}>
                    {n.label}
                  </option>
                ))}
              </select>
            </Field>
          )}
        </fieldset>
      </div>

      <aside className="h-fit rounded-xl border bg-card p-5 lg:sticky lg:top-24">
        <h2 className="mb-3 font-semibold">{t.checkout.summary}</h2>
        <ul className="mb-4 flex flex-col gap-2 text-sm">
          {cart.items.map((line) => (
            <li key={line.product.id} className="flex justify-between gap-3">
              <span className="min-w-0 truncate">
                {line.quantity} × {line.product.name}
              </span>
              <span className="tabular-nums">{formatTZS(line.line_total)}</span>
            </li>
          ))}
        </ul>
        <dl className="flex flex-col gap-1 border-t pt-3 text-sm">
          <div className="flex justify-between">
            <dt>{t.cart.subtotal}</dt>
            <dd className="tabular-nums">{formatTZS(cart.subtotal)}</dd>
          </div>
          <div className="flex justify-between">
            <dt>{t.checkout.deliveryFee}</dt>
            <dd className="tabular-nums">{fee ? formatTZS(fee) : "—"}</dd>
          </div>
          <div className="mt-2 flex justify-between text-base font-semibold">
            <dt>{t.checkout.total}</dt>
            <dd data-testid="checkout-total" className="tabular-nums">
              {total ? formatTZS(total) : "—"}
            </dd>
          </div>
        </dl>
        {formError && (
          <p role="alert" className="mt-4 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
            {formError}
          </p>
        )}
        <Button type="submit" size="lg" className="mt-4 w-full" disabled={formState.isSubmitting || redirecting}>
          {(formState.isSubmitting || redirecting) && <Loader2 className="size-4 animate-spin" />}
          {redirecting ? t.checkout.redirecting : formState.isSubmitting ? t.checkout.placing : t.checkout.placeOrder}
        </Button>
      </aside>
    </form>
  );
}
