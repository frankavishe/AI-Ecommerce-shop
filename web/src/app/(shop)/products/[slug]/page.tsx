import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { ProductSkeleton } from "@/components/shop/skeletons";
import { Price } from "@/components/shop/price";
import { ProductGallery } from "@/components/shop/product-gallery";
import { localized } from "@/i18n/config";
import { getDictionary } from "@/i18n/server";
import { getProduct } from "@/lib/api/server";
import { AddToCart } from "./add-to-cart";

export async function generateMetadata({ params }: PageProps<"/products/[slug]">): Promise<Metadata> {
  const product = await getProduct((await params).slug);
  return product ? { title: product.name, description: product.description?.slice(0, 160) } : {};
}

export default function ProductPage({ params }: PageProps<"/products/[slug]">) {
  return (
    <Suspense fallback={<ProductSkeleton />}>
      <ProductDetail params={params} />
    </Suspense>
  );
}

async function ProductDetail({ params }: { params: PageProps<"/products/[slug]">["params"] }) {
  const { slug } = await params;
  const [product, { locale, t }] = await Promise.all([getProduct(slug), getDictionary()]);
  if (!product) notFound();
  const description = localized(locale, product.description, product.description_sw);
  const categoryName = localized(locale, product.category_name, product.category_name_sw);

  return (
    <div className="grid gap-8 md:grid-cols-2">
      <ProductGallery images={product.images ?? []} name={product.name} />
      <div className="flex flex-col gap-4">
        {categoryName && <p className="text-sm text-muted-foreground">{categoryName}</p>}
        <h1 className="text-2xl font-semibold sm:text-3xl">{product.name}</h1>
        <Price price={product.price} compareAt={product.compare_at_price} className="text-xl" />
        <p className={product.in_stock ? "text-sm text-emerald-700" : "text-sm font-medium text-destructive"}>
          {product.in_stock ? t.catalog.inStock : t.catalog.outOfStock}
        </p>
        <AddToCart productId={product.id} disabled={!product.in_stock} />
        {description && (
          <section className="mt-2 border-t pt-4">
            <h2 className="mb-2 font-semibold">{t.product.description}</h2>
            <p className="whitespace-pre-line text-muted-foreground">{description}</p>
          </section>
        )}
        {product.sku && (
          <p className="text-xs text-muted-foreground">
            {t.product.sku}: {product.sku}
          </p>
        )}
      </div>
    </div>
  );
}
