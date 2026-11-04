"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { bff } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Cart } from "@/lib/api/types";

export const cartKey = ["cart"] as const;
const EMPTY: Cart = { items: [], item_count: 0, subtotal: "0.00" };

export function useCart() {
  return useQuery({ queryKey: cartKey, queryFn: () => bff<Cart>("cart/") });
}

function showError(error: unknown) {
  toast.error(error instanceof ApiError ? error.detail : "Something went wrong. Please try again.");
}

/** Every cart mutation returns the server's cart, which replaces the cached one (FR-005). */
function useCartMutation<V>(fn: (vars: V) => Promise<Cart | null>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (cart) => qc.setQueryData(cartKey, cart ?? EMPTY),
    onError: (error) => {
      showError(error);
      // The server is the source of truth; resync after a refused change.
      qc.invalidateQueries({ queryKey: cartKey });
    },
  });
}

export const useAddItem = () =>
  useCartMutation(({ productId, quantity = 1 }: { productId: number; quantity?: number }) =>
    bff<Cart>("cart/items/", { method: "POST", json: { product_id: productId, quantity } }),
  );

export const useUpdateItem = () =>
  useCartMutation(({ productId, quantity }: { productId: number; quantity: number }) =>
    bff<Cart>(`cart/items/${productId}/`, { method: "PATCH", json: { quantity } }),
  );

export const useRemoveItem = () =>
  useCartMutation(({ productId }: { productId: number }) =>
    bff<Cart>(`cart/items/${productId}/`, { method: "DELETE" }),
  );

export const useClearCart = () => useCartMutation(() => bff<null>("cart/", { method: "DELETE" }));
