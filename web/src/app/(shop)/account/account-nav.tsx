"use client";

import { Loader2, LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n/client";
import { useLogout, useSession } from "@/lib/queries/session";
import { cn } from "@/lib/utils";

export function AccountNav() {
  const { t } = useT();
  const pathname = usePathname();
  const router = useRouter();
  const { data: user } = useSession();
  const logout = useLogout();
  const tabs = [
    { href: "/account", label: t.account.profile },
    { href: "/account/addresses", label: t.account.addresses },
    { href: "/account/orders", label: t.account.orders },
  ];

  const onLogout = async () => {
    await logout.mutateAsync().catch(() => undefined);
    router.push("/");
    router.refresh();
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{t.account.title}</h1>
          {user && <p className="text-sm text-muted-foreground">{user.username}</p>}
        </div>
        <Button variant="outline" size="sm" onClick={onLogout} disabled={logout.isPending}>
          {logout.isPending ? <Loader2 className="size-4 animate-spin" /> : <LogOut className="size-4" />}
          {t.nav.logout}
        </Button>
      </div>
      <nav aria-label={t.account.title} className="flex gap-1 overflow-x-auto border-b">
        {tabs.map((tab) => {
          const active = tab.href === "/account" ? pathname === "/account" : pathname.startsWith(tab.href);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                active ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
