import type { Metadata } from "next";
import { Suspense } from "react";
import { EditProduct } from "./edit-product";

export const metadata: Metadata = { title: "Edit product" };

export default function EditProductPage({ params }: PageProps<"/admin/products/[slug]">) {
  return (
    <Suspense fallback={null}>
      <Load params={params} />
    </Suspense>
  );
}

async function Load({ params }: { params: PageProps<"/admin/products/[slug]">["params"] }) {
  const { slug } = await params;
  return <EditProduct slug={slug} />;
}
