"use client";

import { useQuery } from "@tanstack/react-query";
import { bff } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Order } from "@/lib/api/types";
import { getGuestPhone } from "@/lib/guest-orders";
import { shouldPoll } from "@/lib/order-status";

export const orderKey = (number: string) => ["order", number] as const;

/**
 * Owner view for logged-in customers, otherwise the guest proof (number + phone kept in this tab).
 * Throws ApiError(404) when neither works so the page can send the visitor to /track.
 */
export async function loadOrder(number: string, loggedIn: boolean): Promise<Order> {
  if (loggedIn) {
    try {
      return await bff<Order>(`orders/${encodeURIComponent(number)}/`);
    } catch (error) {
      if (!(error instanceof ApiError) || ![401, 403, 404].includes(error.status)) throw error;
    }
  }
  const phone = getGuestPhone(number);
  if (!phone) throw new ApiError(404, "Not found.", "needs_lookup");
  return bff<Order>("orders/lookup/", { method: "POST", json: { number, phone } });
}

export function useOrder(number: string, loggedIn: boolean, enabled: boolean) {
  return useQuery({
    queryKey: orderKey(number),
    queryFn: () => loadOrder(number, loggedIn),
    enabled,
    // Live status while awaiting payment (FR-010, research R7).
    refetchInterval: (query) => (query.state.data && shouldPoll(query.state.data.status) ? 5_000 : false),
    refetchIntervalInBackground: false,
  });
}
