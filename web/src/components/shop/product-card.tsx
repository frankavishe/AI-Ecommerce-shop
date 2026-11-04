import Link from "next/link";
import type { Product } from "@/lib/api/types";
import { Price } from "./price";
import { ProductImage } from "./product-image";

export function ProductCard({
  product,
  outOfStockLabel,
  eager,
}: {
  product: Product;
  outOfStockLabel: string;
  eager?: boolean;
}) {
  const image = product.images?.[0];
  return (
    <Link
      href={`/products/${product.slug}`}
      className="group flex flex-col gap-2 rounded-xl p-2 transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring"
    >
      <div className="relative">
        <ProductImage
          src={image?.image}
          alt={image?.alt_text || product.name}
          sizes="(min-width: 1024px) 22vw, (min-width: 640px) 30vw, 45vw"
          priority={eager}
          className="transition-transform group-hover:scale-[1.01]"
        />
        {!product.in_stock && (
          <span className="absolute left-2 top-2 rounded-full bg-background/90 px-2 py-0.5 text-xs font-medium">
            {outOfStockLabel}
          </span>
        )}
      </div>
      <span className="line-clamp-2 text-sm font-medium leading-snug">{product.name}</span>
      <Price price={product.price} compareAt={product.compare_at_price} className="text-sm" />
    </Link>
  );
}
