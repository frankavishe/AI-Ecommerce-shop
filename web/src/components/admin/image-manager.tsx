"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Loader2, Trash2, Upload } from "lucide-react";
import Image from "next/image";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { refreshCatalog } from "@/app/admin/actions";
import { Button } from "@/components/ui/button";
import { inputClass } from "@/components/shop/form-field";
import { bff } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { AdminProduct, ProductImage } from "@/lib/api/types";
import { mediaPath } from "@/lib/media";
import { adminKeys } from "@/lib/queries/admin";

const message = (e: unknown) => (e instanceof ApiError ? e.detail : null) ?? "Could not update the images. Try again.";

function ImageRow({
  product,
  image,
  index,
  total,
  onMove,
  busy,
}: {
  product: AdminProduct;
  image: ProductImage;
  index: number;
  total: number;
  onMove: (from: number, to: number) => void;
  busy: boolean;
}) {
  const qc = useQueryClient();
  const [alt, setAlt] = useState(image.alt_text ?? "");
  const [confirming, setConfirming] = useState(false);
  const path = mediaPath(image.image);
  const base = `products/${product.slug}/images/${image.id}/`;
  const done = async () => {
    await refreshCatalog(product.slug);
    await qc.invalidateQueries({ queryKey: adminKeys.product(product.slug) });
  };
  const saveAlt = useMutation({
    mutationFn: () => bff<ProductImage>(base, { method: "PATCH", json: { alt_text: alt.trim() } }),
    onSuccess: async () => {
      await done();
      toast.success("Alt text saved");
    },
    onError: (e) => toast.error(message(e)),
  });
  const remove = useMutation({
    mutationFn: () => bff<null>(base, { method: "DELETE" }),
    onSuccess: async () => {
      await done();
      toast.success("Image deleted");
    },
    onError: (e) => toast.error(message(e)),
  });

  return (
    <li className="flex flex-col gap-3 rounded-lg border p-3 sm:flex-row sm:items-center">
      <div className="relative size-20 shrink-0 overflow-hidden rounded-md bg-muted">
        {path && <Image src={path} alt={image.alt_text || product.name} fill sizes="80px" className="object-cover" />}
      </div>
      <form
        className="flex min-w-0 flex-1 gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          saveAlt.mutate();
        }}
      >
        <input
          aria-label={`Alt text for image ${index + 1}`}
          placeholder="Describe the image for screen readers"
          value={alt}
          onChange={(e) => setAlt(e.target.value)}
          className={inputClass}
        />
        <Button type="submit" variant="outline" size="sm" className="h-10" disabled={saveAlt.isPending || alt === (image.alt_text ?? "")}>
          Save
        </Button>
      </form>
      <div className="flex items-center gap-1">
        <Button type="button" variant="ghost" size="icon" aria-label="Move up" disabled={busy || index === 0} onClick={() => onMove(index, index - 1)}>
          <ArrowUp className="size-4" />
        </Button>
        <Button type="button" variant="ghost" size="icon" aria-label="Move down" disabled={busy || index === total - 1} onClick={() => onMove(index, index + 1)}>
          <ArrowDown className="size-4" />
        </Button>
        {confirming ? (
          <>
            <Button type="button" variant="destructive" size="sm" onClick={() => remove.mutate()} disabled={remove.isPending}>
              {remove.isPending && <Loader2 className="size-4 animate-spin" />}
              Delete
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setConfirming(false)}>
              Keep
            </Button>
          </>
        ) : (
          <Button type="button" variant="ghost" size="icon" aria-label={`Delete image ${index + 1}`} onClick={() => setConfirming(true)}>
            <Trash2 className="size-4" />
          </Button>
        )}
      </div>
    </li>
  );
}

export function ImageManager({ product }: { product: AdminProduct }) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const images = [...product.images].sort((a, b) => (a.position ?? 0) - (b.position ?? 0));

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      let position = images.length ? Math.max(...images.map((i) => i.position ?? 0)) + 1 : 0;
      for (const file of files) {
        const body = new FormData();
        body.append("image", file);
        body.append("position", String(position++));
        await bff<ProductImage>(`products/${product.slug}/images/`, { method: "POST", body });
      }
    },
    onSettled: async () => {
      if (fileRef.current) fileRef.current.value = "";
      await refreshCatalog(product.slug);
      await qc.invalidateQueries({ queryKey: adminKeys.product(product.slug) });
    },
    onSuccess: () => toast.success("Images added"),
    onError: (e) => toast.error(message(e)),
  });

  /** Rewrites positions 0..n-1 in the new order; the first image is the storefront cover. */
  const reorder = useMutation({
    mutationFn: async ({ from, to }: { from: number; to: number }) => {
      const order = [...images];
      const [moved] = order.splice(from, 1);
      order.splice(to, 0, moved);
      await Promise.all(
        order.map((img, position) =>
          img.position === position
            ? null
            : bff(`products/${product.slug}/images/${img.id}/`, { method: "PATCH", json: { position } }),
        ),
      );
    },
    onSettled: async () => {
      await refreshCatalog(product.slug);
      await qc.invalidateQueries({ queryKey: adminKeys.product(product.slug) });
    },
    onError: (e) => toast.error(message(e)),
  });

  return (
    <section className="flex flex-col gap-3 rounded-xl border bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-semibold">Images</h2>
          <p className="text-sm text-muted-foreground">The first image is the cover in the shop.</p>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
          Add images
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          multiple
          aria-label="Add images"
          className="sr-only"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            if (files.length) upload.mutate(files);
          }}
        />
      </div>
      {images.length === 0 ? (
        <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          No images yet. Products without images show a placeholder in the shop.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {images.map((img, i) => (
            <ImageRow
              key={img.id}
              product={product}
              image={img}
              index={i}
              total={images.length}
              busy={reorder.isPending}
              onMove={(from, to) => reorder.mutate({ from, to })}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
