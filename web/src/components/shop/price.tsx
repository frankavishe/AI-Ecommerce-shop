import { formatTZS } from "@/lib/money";
import { cn } from "@/lib/utils";

/** Server price, with the compare-at price struck through when it is higher. */
export function Price({
  price,
  compareAt,
  className,
}: {
  price: string;
  compareAt?: string | null;
  className?: string;
}) {
  const showCompare = compareAt && Number(compareAt) > Number(price);
  return (
    <span className={cn("inline-flex flex-wrap items-baseline gap-x-2", className)}>
      <span className="font-semibold tabular-nums">{formatTZS(price)}</span>
      {showCompare && <s className="text-sm text-muted-foreground tabular-nums">{formatTZS(compareAt)}</s>}
    </span>
  );
}
