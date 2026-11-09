"use client";

import { ExternalLink, LayoutDashboard, Loader2, LogOut, MapPinned, Package, ReceiptText, Tags } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useLogout, useSession } from "@/lib/queries/session";
import { cn } from "@/lib/utils";

const shopName = process.env.NEXT_PUBLIC_SHOP_NAME ?? "Duka";

const LINKS = [
  { href: "/admin", label: "Dashboard", Icon: LayoutDashboard },
  { href: "/admin/products", label: "Products", Icon: Package },
  { href: "/admin/categories", label: "Categories", Icon: Tags },
  { href: "/admin/orders", label: "Orders", Icon: ReceiptText },
  { href: "/admin/delivery-regions", label: "Delivery regions", Icon: MapPinned },
] as const;

export function AdminNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { data: user } = useSession();
  const logout = useLogout();

  const onLogout = async () => {
    await logout.mutateAsync().catch(() => undefined);
    router.push("/");
    router.refresh();
  };

  return (
    <aside className="sticky top-0 z-30 flex shrink-0 flex-col border-b bg-background md:h-screen md:w-60 md:border-b-0 md:border-r">
      <div className="flex items-center justify-between gap-2 px-4 py-3 md:py-5">
        <Link href="/admin" className="font-bold tracking-tight text-primary">
          {shopName} <span className="font-medium text-muted-foreground">Admin</span>
        </Link>
      </div>
      <nav aria-label="Admin" className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-1 md:flex-col md:overflow-visible md:pb-0">
        {LINKS.map(({ href, label, Icon }) => {
          const active = href === "/admin" ? pathname === "/admin" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-2 whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="hidden flex-col gap-1 border-t p-3 text-sm md:flex">
        {user && <p className="truncate px-2 pb-1 text-muted-foreground">Signed in as {user.username}</p>}
        <Link href="/" className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-accent">
          <ExternalLink className="size-4" aria-hidden />
          View shop
        </Link>
        <button
          type="button"
          onClick={onLogout}
          disabled={logout.isPending}
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-accent"
        >
          {logout.isPending ? <Loader2 className="size-4 animate-spin" /> : <LogOut className="size-4" aria-hidden />}
          Log out
        </button>
      </div>
      <div className="flex justify-end gap-3 px-4 pb-2 text-sm md:hidden">
        <Link href="/" className="text-muted-foreground hover:text-foreground">
          View shop
        </Link>
        <button type="button" onClick={onLogout} className="text-muted-foreground hover:text-foreground">
          Log out
        </button>
      </div>
    </aside>
  );
}
