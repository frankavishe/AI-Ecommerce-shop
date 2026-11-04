import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

const PAGE_SIZE = 24;

/** Link-based paging that keeps the other query params (FR-002). */
export function Pagination({
  count,
  page,
  params,
  pathname,
  labels,
}: {
  count: number;
  page: number;
  params: Record<string, string>;
  pathname: string;
  labels: { previous: string; next: string; page: string };
}) {
  const pages = Math.max(1, Math.ceil(count / PAGE_SIZE));
  if (pages <= 1) return null;
  const href = (p: number) => {
    const q = new URLSearchParams({ ...params, page: String(p) });
    if (p === 1) q.delete("page");
    const s = q.toString();
    return s ? `${pathname}?${s}` : pathname;
  };
  return (
    <nav className="flex items-center justify-center gap-3 py-6" aria-label="Pagination">
      <Button variant="outline" size="sm" asChild={page > 1} disabled={page <= 1}>
        {page > 1 ? (
          <Link href={href(page - 1)}>
            <ChevronLeft className="size-4" />
            {labels.previous}
          </Link>
        ) : (
          <>
            <ChevronLeft className="size-4" />
            {labels.previous}
          </>
        )}
      </Button>
      <span className="text-sm text-muted-foreground">
        {labels.page.replace("{page}", String(page)).replace("{pages}", String(pages))}
      </span>
      <Button variant="outline" size="sm" asChild={page < pages} disabled={page >= pages}>
        {page < pages ? (
          <Link href={href(page + 1)}>
            {labels.next}
            <ChevronRight className="size-4" />
          </Link>
        ) : (
          <>
            {labels.next}
            <ChevronRight className="size-4" />
          </>
        )}
      </Button>
    </nav>
  );
}
