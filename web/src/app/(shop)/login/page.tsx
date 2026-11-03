import type { Metadata } from "next";
import { Suspense } from "react";
import { LoginForm } from "@/components/shop/auth-forms";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { safeNext } from "@/lib/guard";

export const metadata: Metadata = { title: "Log in" };

type Search = PageProps<"/login">["searchParams"];

export default function LoginPage({ searchParams }: PageProps<"/login">) {
  return (
    <Suspense fallback={<PanelSkeleton />}>
      <Login searchParams={searchParams} />
    </Suspense>
  );
}

async function Login({ searchParams }: { searchParams: Search }) {
  const { next } = await searchParams;
  return <LoginForm next={safeNext(typeof next === "string" ? next : null)} />;
}
