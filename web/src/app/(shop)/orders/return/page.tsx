"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { getLastOrder } from "@/lib/guest-orders";

/** Where the hosted card checkout sends shoppers back (research R9). */
export default function CardReturnPage() {
  const router = useRouter();
  useEffect(() => {
    const number = getLastOrder();
    router.replace(number ? `/orders/${number}` : "/track");
  }, [router]);
  return <PanelSkeleton />;
}
