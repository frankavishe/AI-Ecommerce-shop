"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { useT } from "@/i18n/client";
import { bff } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Order, PaymentStarted } from "@/lib/api/types";
import { getGuestPhone, setLastOrder } from "@/lib/guest-orders";
import { formatTZS } from "@/lib/money";
import { orderKey } from "@/lib/queries/orders";
import { NETWORKS } from "./checkout-form";

const field = "h-10 w-full rounded-md border border-input bg-background px-3 text-sm";

/** Starts a fresh payment attempt for an order awaiting payment (FR-011). */
export function PayAgainDialog({ order, label }: { order: Order; label: string }) {
  const { t } = useT();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [method, setMethod] = useState<"mobile_money" | "card">("mobile_money");
  const [network, setNetwork] = useState("");
  const [email, setEmail] = useState(order.contact_email ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (method === "card" && !email.trim()) return setError(t.checkout.emailForCard);
    setBusy(true);
    try {
      const body: Record<string, string> = { payment_method: method };
      if (method === "mobile_money" && network) body.network = network;
      if (method === "card") body.email = email.trim();
      const phone = getGuestPhone(order.number);
      if (phone) body.phone = phone;
      const started = await bff<PaymentStarted>(`orders/${order.number}/pay/`, { method: "POST", json: body });
      qc.setQueryData(["payment-error", order.number], null);
      setLastOrder(order.number);
      if (started.payment_method === "card" && started.payment_url) {
        window.location.assign(started.payment_url);
        return;
      }
      toast.success(started.message);
      setOpen(false);
      qc.invalidateQueries({ queryKey: orderKey(order.number) });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t.common.errorBody);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>{label}</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{label}</DialogTitle>
          <DialogDescription>
            {order.number} · {formatTZS(order.total)}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-medium">{t.checkout.payment}</legend>
            {(
              [
                ["mobile_money", t.checkout.mobileMoney],
                ["card", t.checkout.card],
              ] as const
            ).map(([value, text]) => (
              <label key={value} className="flex items-center gap-2 text-sm">
                <input type="radio" name="pay-method" value={value} checked={method === value} onChange={() => setMethod(value)} className="size-4 accent-primary" />
                {text}
              </label>
            ))}
          </fieldset>
          {method === "mobile_money" ? (
            <label className="flex flex-col gap-1 text-sm">
              {t.checkout.network}
              <select value={network} onChange={(e) => setNetwork(e.target.value)} className={field}>
                <option value="">{t.checkout.networkAuto}</option>
                {NETWORKS.map((n) => (
                  <option key={n.value} value={n.value}>{n.label}</option>
                ))}
              </select>
            </label>
          ) : (
            <label className="flex flex-col gap-1 text-sm">
              {t.checkout.email}
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={field} autoComplete="email" />
            </label>
          )}
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <Button type="submit" disabled={busy}>
            {busy && <Loader2 className="size-4 animate-spin" />}
            {label}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
