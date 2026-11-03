import "server-only";
import { cacheLife, cacheTag } from "next/cache";
import createClient from "openapi-fetch";
import type { paths } from "./schema";
import type { Category, DeliveryRegions, Paginated, Product } from "./types";

const baseUrl = (process.env.DJANGO_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

/** Server-side client for public catalog data: no cookies, so Django returns the public serializer. */
const server = createClient<paths>({ baseUrl });

export type CatalogQuery = {
  search?: string;
  category?: string;
  min_price?: string;
  max_price?: string;
  in_stock?: string;
  ordering?: string;
  page?: string;
};

const QUERY_KEYS = ["search", "category", "min_price", "max_price", "in_stock", "ordering", "page"] as const;

/** Picks known catalog params from page searchParams (data-model CatalogQuery). */
export function catalogQuery(sp: Record<string, string | string[] | undefined>): CatalogQuery {
  const q: CatalogQuery = {};
  for (const key of QUERY_KEYS) {
    const v = sp[key];
    const value = Array.isArray(v) ? v[0] : v;
    if (value) q[key] = value;
  }
  return q;
}

export async function getCategories(): Promise<Category[]> {
  "use cache";
  cacheLife("minutes");
  cacheTag("catalog");
  const { data } = await server.GET("/api/categories/");
  const page = data as unknown as Paginated<Category> | Category[] | undefined;
  const list = Array.isArray(page) ? page : (page?.results ?? []);
  return list.filter((c) => c.is_active !== false);
}

export async function getProducts(query: CatalogQuery): Promise<Paginated<Product>> {
  "use cache";
  cacheLife("minutes");
  cacheTag("catalog");
  const { data } = await server.GET("/api/products/", { params: { query: query as never } });
  return (data as Paginated<Product> | undefined) ?? { count: 0, results: [] };
}

export async function getProduct(slug: string): Promise<Product | null> {
  "use cache";
  cacheLife("minutes");
  cacheTag("catalog", `product:${slug}`);
  const { data, response } = await server.GET("/api/products/{slug}/", { params: { path: { slug } } });
  return response.ok && data ? (data as Product) : null;
}

export async function getDeliveryRegions(): Promise<DeliveryRegions> {
  "use cache";
  cacheLife("minutes");
  const { data } = await server.GET("/api/delivery-regions/");
  return (data as DeliveryRegions | undefined) ?? { regions: [], default_fee: "0.00" };
}
