import type { Metadata } from "next";
import { Suspense } from "react";
import { AdminNav } from "./admin-nav";

export const metadata: Metadata = { title: { default: "Admin", template: "%s · Admin" } };

/** Django enforces admin permissions on every call; proxy.ts only keeps others from seeing these pages. */
export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <div lang="en" className="flex min-h-screen flex-col bg-muted/30 md:flex-row">
      <AdminNav />
      <main className="min-w-0 flex-1 px-4 py-6 md:px-8">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
          <Suspense fallback={null}>{children}</Suspense>
        </div>
      </main>
    </div>
  );
}
