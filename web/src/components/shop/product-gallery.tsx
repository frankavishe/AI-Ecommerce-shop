"use client";

import { useState } from "react";
import type { ProductImage as Img } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { ProductImage } from "./product-image";

export function ProductGallery({ images, name }: { images: Img[]; name: string }) {
  const sorted = [...images].sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
  const [active, setActive] = useState(0);
  const current = sorted[active];
  return (
    <div className="flex flex-col gap-3">
      <ProductImage src={current?.image} alt={current?.alt_text || name} sizes="(min-width: 768px) 50vw, 100vw" priority />
      {sorted.length > 1 && (
        <div className="flex gap-2 overflow-x-auto">
          {sorted.map((img, i) => (
            <button
              key={img.id}
              type="button"
              onClick={() => setActive(i)}
              aria-label={`${name} ${i + 1}`}
              aria-current={i === active}
              className={cn("w-16 shrink-0 rounded-lg ring-offset-2", i === active && "ring-2 ring-primary")}
            >
              <ProductImage src={img.image} alt="" sizes="64px" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
