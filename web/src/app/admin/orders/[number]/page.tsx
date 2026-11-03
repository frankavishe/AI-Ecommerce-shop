import type { Metadata } from "next";
import { Suspense } from "react";
import { AdminOrderDetail } from "./order-detail";

export const metadata: Metadata = { title: "Order" };

export default function AdminOrderPage({ params }: PageProps<"/admin/orders/[number]">) {
  return (
    <Suspense fallback={null}>
      <Load params={params} />
    </Suspense>
  );
}

async function Load({ params }: { params: PageProps<"/admin/orders/[number]">["params"] }) {
  const { number } = await params;
  return <AdminOrderDetail number={number.toUpperCase()} />;
}
