"use client";

import Link from "next/link";
import { useT } from "@/i18n/client";

export function Footer() {
  const { t } = useT();
  return (
    <footer className="mt-auto border-t bg-secondary/50">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-8 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <p>{t.common.shopTagline}</p>
        <nav className="flex gap-4" aria-label="Footer">
          <Link href="/track" className="hover:text-foreground">{t.nav.track}</Link>
          <Link href="/products" className="hover:text-foreground">{t.nav.products}</Link>
        </nav>
      </div>
    </footer>
  );
}
