"use client";

import { ShoppingBag, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { Button } from "@/components/ui/button";
import { fmt } from "@/i18n/config";
import { useT } from "@/i18n/client";
import type { CartLine } from "@/lib/api/types";
import { formatTZS } from "@/lib/money";
import { useCart, useClearCart, useRemoveItem, useUpdateItem } from "@/lib/queries/cart";

function QuantityInput({ line }: { line: CartLine }) {
  const { t } = useT();
  const update = useUpdateItem();
  const [value, setValue] = useState(String(line.quantity));

  const commit = () => {
    const quantity = Number(value);
    if (!Number.isInteger(quantity) || quantity < 0) return setValue(String(line.quantity));
    if (quantity === line.quantity) return;
    update.mutate(
      { productId: line.product.id, quantity },
      { onError: () => setValue(String(line.quantity)) },
    );
  };

  return (
    <input
      type="number"
      min={0}
      inputMode="numeric"
      aria-label={`${t.product.quantity}: ${line.product.name}`}
      value={value}
      disabled={update.isPending}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && commit()}
      className="h-9 w-16 rounded-md border border-input bg-background px-2 text-center tabular-nums"
    />
  );
}

export function CartView() {
  const { t } = useT();
  const { data: cart, isLoading, isError, refetch } = useCart();
  const remove = useRemoveItem();
  const clear = useClearCart();

  if (isLoading) return <PanelSkeleton />;
  if (isError || !cart) {
    return (
      <div className="py-16 text-center">
        <p className="mb-4 text-muted-foreground">{t.common.errorBody}</p>
        <Button onClick={() => refetch()}>{t.common.retry}</Button>
      </div>
    );
  }
  if (cart.items.length === 0) {
    return (
      <div className="flex flex-col items-center gap-4 py-16 text-center">
        <ShoppingBag className="size-10 text-muted-foreground" />
        <h1 className="text-xl font-semibold">{t.cart.empty}</h1>
        <Button asChild>
          <Link href="/products">{t.cart.continueShopping}</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
      <section>
        <div className="mb-4 flex items-baseline justify-between">
          <h1 className="text-2xl font-semibold">{t.cart.title}</h1>
          <span className="text-sm text-muted-foreground">{cart.item_count === 1 ? t.cart.itemCountOne : fmt(t.cart.itemCount, { count: cart.item_count })}</span>
        </div>
        <ul className="divide-y rounded-xl border">
          {cart.items.map((line) => (
            <li key={line.product.id} data-testid="cart-line" className="flex flex-wrap items-center gap-3 p-4">
              <div className="min-w-0 flex-1 basis-full sm:basis-0">
                <Link href={`/products/${line.product.slug}`} className="font-medium hover:underline">
                  {line.product.name}
                </Link>
                <p className="text-sm text-muted-foreground tabular-nums">{formatTZS(line.unit_price)}</p>
              </div>
              <QuantityInput key={line.quantity} line={line} />
              <p className="ml-auto w-28 text-right font-semibold tabular-nums sm:ml-0">{formatTZS(line.line_total)}</p>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`${t.cart.remove}: ${line.product.name}`}
                disabled={remove.isPending}
                onClick={() => remove.mutate({ productId: line.product.id })}
              >
                <Trash2 className="size-4" />
              </Button>
            </li>
          ))}
        </ul>
        <Button variant="link" className="mt-2 px-0 text-muted-foreground" disabled={clear.isPending} onClick={() => clear.mutate()}>
          {t.cart.clear}
        </Button>
      </section>

      <aside className="h-fit rounded-xl border bg-card p-5">
        <div className="flex items-baseline justify-between">
          <span>{t.cart.subtotal}</span>
          <span className="text-lg font-semibold tabular-nums">{formatTZS(cart.subtotal)}</span>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">{t.cart.deliveryNote}</p>
        <Button asChild size="lg" className="mt-4 w-full">
          <Link href="/checkout">{t.cart.checkout}</Link>
        </Button>
      </aside>
    </div>
  );
}
