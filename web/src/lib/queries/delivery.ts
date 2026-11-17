"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { bff } from "@/lib/api/client";
import type { DeliveryDetail, DeliveryListItem, DeliveryStatus, Paginated, RiderCandidate } from "@/lib/api/types";

export const deliveryKeys = {
  list: (q: string) => ["admin", "deliveries", q] as const,
  detail: (id: number) => ["admin", "delivery", id] as const,
  candidates: (id: number) => ["admin", "delivery", id, "candidates"] as const,
  forOrder: (number: string) => ["admin", "deliveries", "order", number] as const,
};

export const useDeliveries = (query: string) =>
  useQuery({
    queryKey: deliveryKeys.list(query),
    queryFn: () => bff<Paginated<DeliveryListItem>>(`admin/deliveries/${query}`),
    placeholderData: keepPreviousData,
  });

export const useDelivery = (id: number) =>
  useQuery({ queryKey: deliveryKeys.detail(id), queryFn: () => bff<DeliveryDetail>(`admin/deliveries/${id}/`) });

export const useCandidates = (id: number, enabled = true) =>
  useQuery({
    queryKey: deliveryKeys.candidates(id),
    queryFn: () => bff<RiderCandidate[]>(`admin/deliveries/${id}/candidates/`),
    enabled,
  });

/** The delivery of one order, or null (the admin order page links to it). */
export const useOrderDelivery = (number: string) =>
  useQuery({
    queryKey: deliveryKeys.forOrder(number),
    queryFn: async () =>
      (await bff<Paginated<DeliveryListItem>>(`admin/deliveries/?order=${encodeURIComponent(number)}`)).results[0] ?? null,
  });

/** Writes return the fresh delivery; this stores it and refreshes the lists and the order. */
export function useDeliveryActions(id: number) {
  const qc = useQueryClient();
  const post = async (action: string, json?: unknown) => {
    try {
      const updated = await bff<DeliveryDetail>(`admin/deliveries/${id}/${action}/`, { method: "POST", json });
      qc.setQueryData(deliveryKeys.detail(id), updated);
      return updated;
    } finally {
      // also after a 409 `stale`: show what is there now
      qc.invalidateQueries({ queryKey: deliveryKeys.detail(id) });
      qc.invalidateQueries({ queryKey: ["admin", "deliveries"] });
      qc.invalidateQueries({ queryKey: ["admin", "order"] });
      qc.invalidateQueries({ queryKey: deliveryKeys.candidates(id) });
    }
  };
  return {
    assign: (rider: number, expected_status: DeliveryStatus, expected_rider: number | null) =>
      post("assign", { rider, expected_status, expected_rider }),
    unassign: (expected_rider: number | null) => post("unassign", { expected_rider }),
    setStatus: (status: "picked_up" | "on_the_way" | "delivered" | "failed", note: string, expected_status: DeliveryStatus) =>
      post("status", { status, note, expected_status }),
  };
}

/** Riders for filters (small list: fetch every page). */
export type RiderOption = { id: number; user_id: number; first_name: string; last_name: string; phone: string };

export const useRiderOptions = () =>
  useQuery({
    queryKey: ["admin", "riders", "options"],
    queryFn: async () => {
      const out: RiderOption[] = [];
      for (let page = 1; ; page += 1) {
        const data = await bff<Paginated<RiderOption> | RiderOption[]>(`auth/riders/?page=${page}`);
        if (Array.isArray(data)) return data;
        out.push(...data.results);
        if (!data.next) return out;
      }
    },
  });

export async function createDelivery(number: string) {
  return bff<DeliveryDetail>(`admin/orders/${encodeURIComponent(number)}/delivery/`, { method: "POST" });
}
