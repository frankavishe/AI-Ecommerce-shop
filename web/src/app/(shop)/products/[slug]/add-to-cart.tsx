"use client";

import { Minus, Plus, ShoppingBag } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n/client";
import { useAddItem } from "@/lib/queries/cart";

export function AddToCart({ productId, disabled }: { productId: number; disabled: boolean }) {
  const { t } = useT();
  const [quantity, setQuantity] = useState(1);
  const add = useAddItem();
  const router = useRouter();

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex items-center rounded-md border" role="group" aria-label={t.product.quantity}>
        <Button variant="ghost" size="icon" aria-label="-" disabled={disabled || quantity <= 1} onClick={() => setQuantity((q) => Math.max(1, q - 1))}>
          <Minus className="size-4" />
        </Button>
        <span className="w-8 text-center tabular-nums" aria-live="polite">{quantity}</span>
        <Button variant="ghost" size="icon" aria-label="+" disabled={disabled} onClick={() => setQuantity((q) => q + 1)}>
          <Plus className="size-4" />
        </Button>
      </div>
      <Button
        size="lg"
        disabled={disabled || add.isPending}
        onClick={() =>
          add.mutate(
            { productId, quantity },
            {
              onSuccess: () =>
                toast.success(t.product.added, {
                  action: { label: t.product.viewCart, onClick: () => router.push("/cart") },
                }),
            },
          )
        }
      >
        <ShoppingBag className="size-4" />
        {t.product.addToCart}
      </Button>
      {disabled && (
        <p className="w-full text-sm text-muted-foreground">
          {t.product.unavailable}{" "}
          <Link href="/products" className="text-primary hover:underline">{t.cart.continueShopping}</Link>
        </p>
      )}
    </div>
  );
}
