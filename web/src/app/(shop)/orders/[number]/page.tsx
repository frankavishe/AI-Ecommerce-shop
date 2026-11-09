import { Suspense } from "react";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { OrderView } from "@/components/shop/order-view";

export default function OrderPage({ params, searchParams }: PageProps<"/orders/[number]">) {
  return (
    <Suspense fallback={<PanelSkeleton />}>
      <Order params={params} searchParams={searchParams} />
    </Suspense>
  );
}

async function Order({
  params,
  searchParams,
}: {
  params: PageProps<"/orders/[number]">["params"];
  searchParams: PageProps<"/orders/[number]">["searchParams"];
}) {
  const [{ number }, sp] = await Promise.all([params, searchParams]);
  return <OrderView number={number.toUpperCase()} pending={sp.pending === "1"} />;
}
