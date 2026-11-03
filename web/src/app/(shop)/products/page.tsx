import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { GridSkeleton } from "@/components/shop/skeletons";
import { Pagination } from "@/components/shop/pagination";
import { ProductCard } from "@/components/shop/product-card";
import { Button } from "@/components/ui/button";
import { fmt, localized } from "@/i18n/config";
import { getDictionary } from "@/i18n/server";
import { catalogQuery, getCategories, getProducts } from "@/lib/api/server";

export const metadata: Metadata = { title: "Products" };

const field = "h-10 w-full rounded-md border border-input bg-background px-3 text-sm";

export default function ProductsPage({ searchParams }: PageProps<"/products">) {
  return (
    <Suspense fallback={<GridSkeleton count={12} />}>
      <Catalog searchParams={searchParams} />
    </Suspense>
  );
}

async function Catalog({ searchParams }: { searchParams: PageProps<"/products">["searchParams"] }) {
  const query = catalogQuery(await searchParams);
  const [{ locale, t }, categories, data] = await Promise.all([getDictionary(), getCategories(), getProducts(query)]);
  const page = Math.max(1, Number(query.page) || 1);
  const { page: _page, ...keep } = query;
  void _page;
  const active = categories.find((c) => c.slug === query.category);
  const hasFilters = Object.keys(keep).length > 0;

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <aside className="lg:w-60 lg:shrink-0">
        <details className="group rounded-xl border p-4 lg:open:block" open>
          <summary className="cursor-pointer font-semibold lg:pointer-events-none lg:list-none">{t.catalog.filters}</summary>
          <form action="/products" className="mt-4 flex flex-col gap-4">
            {query.search && <input type="hidden" name="search" value={query.search} />}
            <label className="flex flex-col gap-1 text-sm">
              {t.catalog.category}
              <select name="category" defaultValue={query.category ?? ""} className={field}>
                <option value="">{t.catalog.allCategories}</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.slug}>{localized(locale, c.name, c.name_sw)}</option>
                ))}
              </select>
            </label>
            <fieldset className="flex flex-col gap-1 text-sm">
              <legend className="mb-1">{t.catalog.priceRange}</legend>
              <div className="flex gap-2">
                <input name="min_price" type="number" min={0} inputMode="numeric" defaultValue={query.min_price} placeholder={t.catalog.minPrice} aria-label={t.catalog.minPrice} className={field} />
                <input name="max_price" type="number" min={0} inputMode="numeric" defaultValue={query.max_price} placeholder={t.catalog.maxPrice} aria-label={t.catalog.maxPrice} className={field} />
              </div>
            </fieldset>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" name="in_stock" value="true" defaultChecked={query.in_stock === "true"} className="size-4 accent-primary" />
              {t.catalog.inStockOnly}
            </label>
            <label className="flex flex-col gap-1 text-sm">
              {t.catalog.sortBy}
              <select name="ordering" defaultValue={query.ordering ?? "-created_at"} className={field}>
                <option value="-created_at">{t.catalog.sortNewest}</option>
                <option value="price">{t.catalog.sortPriceLow}</option>
                <option value="-price">{t.catalog.sortPriceHigh}</option>
                <option value="name">{t.catalog.sortName}</option>
              </select>
            </label>
            <Button type="submit">{t.catalog.apply}</Button>
            {hasFilters && (
              <Link href="/products" className="text-center text-sm text-primary hover:underline">{t.catalog.clearFilters}</Link>
            )}
          </form>
        </details>
      </aside>

      <section className="flex-1">
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
          <h1 className="text-2xl font-semibold">
            {active ? localized(locale, active.name, active.name_sw) : query.search ? `“${query.search}”` : t.catalog.title}
          </h1>
          <p className="text-sm text-muted-foreground">{fmt(t.catalog.resultCount, { count: data.count })}</p>
        </div>
        {data.results.length === 0 ? (
          <div className="rounded-xl border border-dashed p-10 text-center text-muted-foreground">
            <p>{t.catalog.noResults}</p>
            <Link href="/products" className="mt-2 inline-block text-primary hover:underline">{t.catalog.clearFilters}</Link>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4">
            {data.results.map((p, i) => (
              <ProductCard key={p.id} product={p} eager={i < 4} outOfStockLabel={t.catalog.outOfStock} />
            ))}
          </div>
        )}
        <Pagination
          count={data.count}
          page={page}
          params={keep as Record<string, string>}
          pathname="/products"
          labels={{ previous: t.common.previous, next: t.common.next, page: t.common.page }}
        />
      </section>
    </div>
  );
}
