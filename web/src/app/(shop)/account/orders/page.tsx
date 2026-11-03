import type { Metadata } from "next";
import { Suspense } from "react";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { OrderHistory } from "./order-history";

export const metadata: Metadata = { title: "Orders" };

type Search = PageProps<"/account/orders">["searchParams"];

export default function OrdersPage({ searchParams }: PageProps<"/account/orders">) {
  return (
    <Suspense fallback={<PanelSkeleton />}>
      <Orders searchParams={searchParams} />
    </Suspense>
  );
}

async function Orders({ searchParams }: { searchParams: Search }) {
  const { page } = await searchParams;
  const n = Number(typeof page === "string" ? page : 1);
  return <OrderHistory page={Number.isInteger(n) && n > 0 ? n : 1} />;
}
