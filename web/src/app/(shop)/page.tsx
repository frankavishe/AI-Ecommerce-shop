import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { ProductCard } from "@/components/shop/product-card";
import { Button } from "@/components/ui/button";
import { localized } from "@/i18n/config";
import { getDictionary } from "@/i18n/server";
import { getCategories, getProducts } from "@/lib/api/server";

export default async function HomePage() {
  const [{ locale, t }, categories, products] = await Promise.all([
    getDictionary(),
    getCategories(),
    getProducts({ ordering: "-created_at" }),
  ]);

  return (
    <div className="flex flex-col gap-10">
      <section className="overflow-hidden rounded-2xl bg-primary px-6 py-10 text-primary-foreground sm:px-10 sm:py-14">
        <h1 className="max-w-xl text-3xl font-bold tracking-tight sm:text-4xl">{t.home.heroTitle}</h1>
        <p className="mt-3 max-w-xl text-primary-foreground/85">{t.home.heroBody}</p>
        <Button asChild size="lg" variant="secondary" className="mt-6">
          <Link href="/products">
            {t.home.shopNow}
            <ArrowRight className="size-4" />
          </Link>
        </Button>
      </section>

      {categories.length > 0 && (
        <section aria-labelledby="categories">
          <h2 id="categories" className="mb-3 text-lg font-semibold">{t.home.categories}</h2>
          <ul className="flex flex-wrap gap-2">
            {categories.map((c) => (
              <li key={c.id}>
                <Link
                  href={`/products?category=${c.slug}`}
                  className="inline-flex rounded-full border bg-background px-4 py-2 text-sm font-medium hover:border-primary hover:text-primary"
                >
                  {localized(locale, c.name, c.name_sw)}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="new-arrivals">
        <div className="mb-3 flex items-center justify-between">
          <h2 id="new-arrivals" className="text-lg font-semibold">{t.home.newArrivals}</h2>
          <Link href="/products" className="text-sm font-medium text-primary hover:underline">{t.home.viewAll}</Link>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {products.results.slice(0, 8).map((p, i) => (
            <ProductCard key={p.id} product={p} eager={i < 4} outOfStockLabel={t.catalog.outOfStock} />
          ))}
        </div>
      </section>
    </div>
  );
}
