"use client";

import { Search, ShoppingBag, User as UserIcon } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n/client";
import { useCart } from "@/lib/queries/cart";
import { useSession } from "@/lib/queries/session";
import { LanguageSwitch } from "./language-switch";

const shopName = process.env.NEXT_PUBLIC_SHOP_NAME ?? "Duka";

function SearchBox({ className }: { className?: string }) {
  const { t } = useT();
  const params = useSearchParams();
  return (
    <form action="/products" role="search" className={className}>
      <label className="relative block">
        <span className="sr-only">{t.common.search}</span>
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <input
          type="search"
          name="search"
          aria-label={t.common.search}
          defaultValue={params.get("search") ?? ""}
          placeholder={t.common.searchPlaceholder}
          className="h-10 w-full rounded-full border border-input bg-background pl-9 pr-4 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        />
      </label>
    </form>
  );
}

function CartButton() {
  const { t } = useT();
  const { data } = useCart();
  const count = data?.item_count ?? 0;
  return (
    <Button variant="ghost" size="sm" asChild>
      <Link href="/cart" aria-label={t.nav.cart} className="relative">
        <ShoppingBag className="size-5" />
        <span className="hidden sm:inline">{t.nav.cart}</span>
        {count > 0 && (
          <span
            data-testid="cart-count"
            className="absolute -right-1 -top-1 flex min-w-5 items-center justify-center rounded-full bg-primary px-1 text-xs font-semibold text-primary-foreground sm:static sm:ml-1"
          >
            {count}
          </span>
        )}
      </Link>
    </Button>
  );
}

function AccountButton() {
  const { t } = useT();
  const { data: user } = useSession();
  const href = user ? (user.role === "admin" ? "/admin" : "/account") : "/login";
  const label = user ? (user.role === "admin" ? t.nav.admin : t.nav.account) : t.nav.login;
  return (
    <Button variant="ghost" size="sm" asChild>
      <Link href={href} aria-label={label}>
        <UserIcon className="size-5" />
        <span className="hidden sm:inline">{label}</span>
      </Link>
    </Button>
  );
}

export function Header() {
  const { t } = useT();
  return (
    <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-2 px-4 py-3 sm:gap-4">
        <Link href="/" className="shrink-0 text-lg font-bold tracking-tight text-primary">
          {shopName}
        </Link>
        <Suspense fallback={<div className="hidden flex-1 md:block" />}>
          <SearchBox className="hidden flex-1 md:block" />
        </Suspense>
        <nav className="ml-auto flex items-center gap-1" aria-label="Main">
          <Button variant="ghost" size="sm" asChild className="hidden sm:inline-flex">
            <Link href="/products">{t.nav.products}</Link>
          </Button>
          <LanguageSwitch />
          <AccountButton />
          <CartButton />
        </nav>
      </div>
      <Suspense fallback={null}>
        <SearchBox className="px-4 pb-3 md:hidden" />
      </Suspense>
    </header>
  );
}
