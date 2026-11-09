import type { Metadata } from "next";
import { Suspense } from "react";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { TrackForm } from "./track-form";

export const metadata: Metadata = { title: "Track order" };

type Search = PageProps<"/track">["searchParams"];

export default function TrackPage({ searchParams }: PageProps<"/track">) {
  return (
    <Suspense fallback={<PanelSkeleton />}>
      <Track searchParams={searchParams} />
    </Suspense>
  );
}

async function Track({ searchParams }: { searchParams: Search }) {
  const { number } = await searchParams;
  return <TrackForm initialNumber={typeof number === "string" ? number.trim().toUpperCase().slice(0, 32) : ""} />;
}
