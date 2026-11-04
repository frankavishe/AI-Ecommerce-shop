import { ImageOff } from "lucide-react";
import Image from "next/image";
import { mediaPath } from "@/lib/media";
import { cn } from "@/lib/utils";

export function ProductImage({
  src,
  alt,
  sizes,
  priority,
  className,
}: {
  src?: string | null;
  alt: string;
  sizes: string;
  priority?: boolean;
  className?: string;
}) {
  const path = mediaPath(src);
  return (
    <div className={cn("relative aspect-square overflow-hidden rounded-lg bg-muted", className)}>
      {path ? (
        <Image src={path} alt={alt} fill sizes={sizes} preload={priority} loading={priority ? "eager" : undefined} className="object-cover" />
      ) : (
        <div className="flex h-full items-center justify-center text-muted-foreground">
          <ImageOff className="size-8" aria-hidden />
        </div>
      )}
    </div>
  );
}
