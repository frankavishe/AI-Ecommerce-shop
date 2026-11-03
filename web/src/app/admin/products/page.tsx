"use client";

import { ImageOff, Plus, Search } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useState } from "react";
import { inputClass } from "@/components/shop/form-field";
import { Pagination } from "@/components/shop/pagination";
import { EmptyRow, ErrorState, PageHeader, plural, tableWrap, td, th, useUrlParams } from "@/components/admin/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { mediaPath } from "@/lib/media";
import { formatTZS } from "@/lib/money";
import { toQuery, useAdminCategories, useAdminProducts } from "@/lib/queries/admin";

const KEYS = ["search", "category", "is_active", "in_stock"] as const;

export default function AdminProductsPage() {
  const { values, page, set, raw } = useUrlParams(KEYS);
  const query = toQuery({ ...values, ordering: "-created_at", page: page > 1 ? String(page) : undefined });
  const products = useAdminProducts(query);
  const categories = useAdminCategories();
  const [search, setSearch] = useState(values.search);

  const select = cn(inputClass, "w-auto min-w-36");

  return (
    <>
      <PageHeader
        title="Products"
        description={products.data ? plural(products.data.count, "product") : undefined}
        actions={
          <Button asChild>
            <Link href="/admin/products/new">
              <Plus className="size-4" />
              New product
            </Link>
          </Button>
        }
      />

      <div className="flex flex-wrap items-end gap-2">
        <form
          role="search"
          className="relative min-w-52 flex-1"
          onSubmit={(e) => {
            e.preventDefault();
            set({ search: search.trim() });
          }}
        >
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            aria-label="Search products"
            placeholder="Search name, SKU, tags…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={cn(inputClass, "pl-9")}
          />
        </form>
        <select aria-label="Category" className={select} value={values.category} onChange={(e) => set({ category: e.target.value })}>
          <option value="">All categories</option>
          {categories.data?.map((c) => (
            <option key={c.id} value={c.slug}>
              {c.name}
            </option>
          ))}
        </select>
        <select aria-label="Visibility" className={select} value={values.is_active} onChange={(e) => set({ is_active: e.target.value })}>
          <option value="">Active and hidden</option>
          <option value="true">Active</option>
          <option value="false">Hidden</option>
        </select>
        <select aria-label="Stock" className={select} value={values.in_stock} onChange={(e) => set({ in_stock: e.target.value })}>
          <option value="">Any stock</option>
          <option value="true">In stock</option>
          <option value="false">Out of stock</option>
        </select>
      </div>

      {products.isError ? (
        <ErrorState onRetry={() => products.refetch()} />
      ) : (
        <div className={tableWrap} aria-busy={products.isFetching}>
          <table className="w-full min-w-[640px] text-sm">
            <thead className="border-b bg-muted/50">
              <tr>
                <th className={th}>Product</th>
                <th className={th}>Category</th>
                <th className={`${th} text-right`}>Price</th>
                <th className={`${th} text-right`}>Stock</th>
                <th className={th}>Status</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {products.isLoading &&
                Array.from({ length: 5 }, (_, i) => (
                  <tr key={i}>
                    <td colSpan={5} className="p-3">
                      <Skeleton className="h-10 w-full" />
                    </td>
                  </tr>
                ))}
              {products.data?.results.length === 0 && <EmptyRow colSpan={5}>No products match these filters.</EmptyRow>}
              {products.data?.results.map((p) => {
                const img = mediaPath(p.images[0]?.image);
                return (
                  <tr key={p.id} className="hover:bg-muted/40">
                    <td className={td}>
                      <Link href={`/admin/products/${p.slug}`} className="flex items-center gap-3">
                        <span className="relative flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-md bg-muted">
                          {img ? <Image src={img} alt="" fill sizes="40px" className="object-cover" /> : <ImageOff className="size-4 text-muted-foreground" />}
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate font-medium hover:underline">{p.name}</span>
                          <span className="block text-xs text-muted-foreground">{p.sku || "No SKU"}</span>
                        </span>
                      </Link>
                    </td>
                    <td className={`${td} text-muted-foreground`}>{p.category_name || "—"}</td>
                    <td className={`${td} text-right tabular-nums`}>{formatTZS(p.price)}</td>
                    <td className={`${td} text-right tabular-nums ${p.stock <= p.low_stock_threshold ? "font-semibold text-amber-700" : ""}`}>
                      {p.stock}
                    </td>
                    <td className={td}>
                      {p.is_active ? <Badge variant="secondary">Active</Badge> : <Badge variant="outline">Hidden</Badge>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {products.data && (
        <Pagination
          count={products.data.count}
          page={page}
          params={Object.fromEntries([...raw.entries()].filter(([k]) => k !== "page"))}
          pathname="/admin/products"
          labels={{ previous: "Previous", next: "Next", page: "Page {page} of {pages}" }}
        />
      )}
    </>
  );
}
