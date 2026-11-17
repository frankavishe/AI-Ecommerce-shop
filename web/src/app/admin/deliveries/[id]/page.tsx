import type { Metadata } from "next";
import { Suspense } from "react";
import { AdminDeliveryDetail } from "./delivery-detail";

export const metadata: Metadata = { title: "Delivery" };

export default function AdminDeliveryPage({ params }: PageProps<"/admin/deliveries/[id]">) {
  return (
    <Suspense fallback={null}>
      <Load params={params} />
    </Suspense>
  );
}

async function Load({ params }: { params: PageProps<"/admin/deliveries/[id]">["params"] }) {
  const { id } = await params;
  return <AdminDeliveryDetail id={Number(id)} />;
}
