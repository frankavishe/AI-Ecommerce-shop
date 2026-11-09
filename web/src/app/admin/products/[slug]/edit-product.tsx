"use client";

import Link from "next/link";
import { ImageManager } from "@/components/admin/image-manager";
import { ProductForm } from "@/components/admin/product-form";
import { ErrorState, PageHeader } from "@/components/admin/ui";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { Badge } from "@/components/ui/badge";
import { ApiError } from "@/lib/api/errors";
import { useAdminProduct } from "@/lib/queries/admin";

export function EditProduct({ slug }: { slug: string }) {
  const product = useAdminProduct(slug);
  const back = (
    <Link href="/admin/products" className="text-sm text-muted-foreground hover:text-foreground">
      ← Products
    </Link>
  );

  if (product.isLoading) return <PanelSkeleton />;
  if (product.error instanceof ApiError && product.error.status === 404) {
    return (
      <>
        {back}
        <PageHeader title="Product not found" description="It may have been deleted." />
      </>
    );
  }
  if (product.isError || !product.data) return <ErrorState onRetry={() => product.refetch()} />;

  const p = product.data;
  return (
    <>
      {back}
      <PageHeader
        title={p.name}
        description={`/${p.slug}`}
        actions={p.is_active ? <Badge variant="secondary">Active</Badge> : <Badge variant="outline">Hidden</Badge>}
      />
      {/* Remount on every save so the form starts from the server's copy. */}
      <ProductForm key={p.updated_at} product={p} />
      <ImageManager product={p} />
    </>
  );
}
