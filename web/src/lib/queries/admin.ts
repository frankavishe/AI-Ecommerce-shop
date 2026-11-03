"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { bff } from "@/lib/api/client";
import type {
  AdminDeliveryRegion,
  AdminOrder,
  AdminOrderSummary,
  AdminProduct,
  Category,
  Paginated,
} from "@/lib/api/types";

/** Drops empty values so URLs and query keys stay canonical. */
export function toQuery(params: Record<string, string | undefined>) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v);
  const s = q.toString();
  return s ? `?${s}` : "";
}

/** DRF list endpoints may be paginated or plain arrays; admin tables want every row. */
async function all<T>(path: string): Promise<T[]> {
  const out: T[] = [];
  let page = 1;
  for (;;) {
    const data = await bff<Paginated<T> | T[]>(`${path}${path.includes("?") ? "&" : "?"}page=${page}`);
    if (Array.isArray(data)) return data;
    out.push(...data.results);
    if (!data.next) return out;
    page += 1;
  }
}

export const adminKeys = {
  products: (q: string) => ["admin", "products", q] as const,
  product: (slug: string) => ["admin", "product", slug] as const,
  categories: ["admin", "categories"] as const,
  orders: (q: string) => ["admin", "orders", q] as const,
  order: (number: string) => ["admin", "order", number] as const,
  regions: ["admin", "regions"] as const,
  lowStock: ["admin", "low-stock"] as const,
  count: (status: string) => ["admin", "count", status] as const,
};

export const useAdminProducts = (query: string) =>
  useQuery({
    queryKey: adminKeys.products(query),
    queryFn: () => bff<Paginated<AdminProduct>>(`products/${query}`),
    placeholderData: keepPreviousData,
  });

export const useAdminProduct = (slug: string) =>
  useQuery({
    queryKey: adminKeys.product(slug),
    queryFn: () => bff<AdminProduct>(`products/${encodeURIComponent(slug)}/`),
  });

/** Includes inactive categories (the endpoint shows them to admins). */
export const useAdminCategories = () =>
  useQuery({ queryKey: adminKeys.categories, queryFn: () => all<Category>("categories/") });

export const useAdminOrders = (query: string) =>
  useQuery({
    queryKey: adminKeys.orders(query),
    queryFn: () => bff<Paginated<AdminOrderSummary>>(`admin/orders/${query}`),
    placeholderData: keepPreviousData,
  });

export const useAdminOrder = (number: string) =>
  useQuery({
    queryKey: adminKeys.order(number),
    queryFn: () => bff<AdminOrder>(`admin/orders/${encodeURIComponent(number)}/`),
  });

export const useAdminRegions = () =>
  useQuery({ queryKey: adminKeys.regions, queryFn: () => all<AdminDeliveryRegion>("admin/delivery-regions/") });

export const useLowStock = () =>
  useQuery({ queryKey: adminKeys.lowStock, queryFn: () => bff<AdminProduct[]>("products/low_stock/") });

/** Order count for a status, read from the paginated list's `count`. */
export const useOrderCount = (status: string) =>
  useQuery({
    queryKey: adminKeys.count(status),
    queryFn: async () => (await bff<Paginated<AdminOrderSummary>>(`admin/orders/?status=${status}`)).count,
  });
