import type { Metadata } from "next";
import { Suspense } from "react";
import { RegisterForm } from "@/components/shop/auth-forms";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { safeNext } from "@/lib/guard";

export const metadata: Metadata = { title: "Create account" };

type Search = PageProps<"/register">["searchParams"];

export default function RegisterPage({ searchParams }: PageProps<"/register">) {
  return (
    <Suspense fallback={<PanelSkeleton />}>
      <Register searchParams={searchParams} />
    </Suspense>
  );
}

async function Register({ searchParams }: { searchParams: Search }) {
  const { next } = await searchParams;
  return <RegisterForm next={safeNext(typeof next === "string" ? next : null)} />;
}
