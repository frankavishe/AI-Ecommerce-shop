"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { en } from "@/i18n/en";
import type { OrderStatus } from "@/lib/api/types";
import { statusTone, TONE_CLASS } from "@/lib/order-status";
import { cn } from "@/lib/utils";

/** Admin is English-only, so it reads the English dictionary directly. */
export const statusLabel = (s: OrderStatus) => en.order.statuses[s];

export function StatusBadge({ status, testId }: { status: OrderStatus; testId?: string }) {
  return (
    <span
      data-testid={testId}
      className={cn("inline-flex whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium", TONE_CLASS[statusTone(status)])}
    >
      {statusLabel(status)}
    </span>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border p-6">
      <p>Could not load this data. Check the connection and try again.</p>
      <Button variant="outline" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
      {message}
    </p>
  );
}

export function EmptyRow({ colSpan, children }: { colSpan: number; children: ReactNode }) {
  return (
    <tr>
      <td colSpan={colSpan} className="p-8 text-center text-muted-foreground">
        {children}
      </td>
    </tr>
  );
}

/** URL-backed filters: reading, and replacing some params while resetting the page. */
export function useUrlParams<K extends string>(keys: readonly K[]) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const values = Object.fromEntries(keys.map((k) => [k, params.get(k) ?? ""])) as Record<K, string>;
  const page = Math.max(1, Number(params.get("page")) || 1);
  const set = useCallback(
    (changes: Partial<Record<K | "page", string>>) => {
      const next = new URLSearchParams(params.toString());
      if (!("page" in changes)) next.delete("page");
      for (const [k, v] of Object.entries(changes) as [string, string | undefined][]) {
        if (v) next.set(k, v);
        else next.delete(k);
      }
      const s = next.toString();
      router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );
  return { values, page, set, raw: params };
}

export const tableWrap = "overflow-x-auto rounded-xl border bg-card";
export const th = "px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground";
export const td = "px-3 py-2 align-middle";
