"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { refreshCatalog } from "@/app/admin/actions";
import { FormError } from "@/components/admin/ui";
import { describedBy, Field, inputClass } from "@/components/shop/form-field";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { Button } from "@/components/ui/button";
import { bff } from "@/lib/api/client";
import type { AdminProduct } from "@/lib/api/types";
import { applyServerErrors } from "@/lib/forms";
import { compareMoney, isMoney } from "@/lib/money";
import { adminKeys, useAdminCategories } from "@/lib/queries/admin";
import { cn } from "@/lib/utils";

const count = (label: string) =>
  z
    .string()
    .trim()
    .regex(/^\d+$/, `${label} must be a whole number of 0 or more.`);

const schema = z
  .object({
    name: z.string().trim().min(1, "Name is required.").max(200),
    sku: z.string().trim().max(64),
    category: z.string(),
    description: z.string(),
    description_sw: z.string(),
    price: z
      .string()
      .trim()
      .refine(isMoney, "Enter a price like 12000 or 12000.50.")
      .refine((v) => compareMoney(v, "0") === 1, "Price must be greater than zero."),
    compare_at_price: z
      .string()
      .trim()
      .refine((v) => !v || isMoney(v), "Enter an amount like 15000."),
    stock: count("Stock"),
    low_stock_threshold: count("Alert level"),
    tags: z.string().trim().max(255),
    is_active: z.boolean(),
  })
  .superRefine((v, ctx) => {
    if (v.compare_at_price && isMoney(v.price) && compareMoney(v.compare_at_price, v.price) !== 1) {
      ctx.addIssue({ code: "custom", path: ["compare_at_price"], message: "Compare-at price must be higher than the price." });
    }
  });
type Values = z.infer<typeof schema>;

function initial(p?: AdminProduct): Values {
  const amount = (v?: string | null) => (v ? v.replace(/\.00$/, "") : "");
  return {
    name: p?.name ?? "",
    sku: p?.sku ?? "",
    category: p?.category ? String(p.category) : "",
    description: p?.description ?? "",
    description_sw: p?.description_sw ?? "",
    price: amount(p?.price),
    compare_at_price: amount(p?.compare_at_price),
    stock: String(p?.stock ?? 0),
    low_stock_threshold: String(p?.low_stock_threshold ?? 5),
    tags: p?.tags ?? "",
    is_active: p?.is_active ?? true,
  };
}

function payload(v: Values) {
  return {
    name: v.name,
    sku: v.sku || null,
    category: v.category ? Number(v.category) : null,
    description: v.description,
    description_sw: v.description_sw,
    price: v.price,
    compare_at_price: v.compare_at_price || null,
    stock: Number(v.stock),
    low_stock_threshold: Number(v.low_stock_threshold),
    tags: v.tags,
    is_active: v.is_active,
  };
}

export function ProductForm({ product }: { product?: AdminProduct }) {
  const router = useRouter();
  const qc = useQueryClient();
  const categories = useAdminCategories();
  const [files, setFiles] = useState<File[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: initial(product) });
  const { register, handleSubmit, formState, reset } = form;
  const errors = formState.errors;

  const onSubmit = handleSubmit(async (v) => {
    setFormError(null);
    try {
      let saved: AdminProduct;
      if (product) {
        saved = await bff<AdminProduct>(`products/${product.slug}/`, { method: "PATCH", json: payload(v) });
      } else {
        // Multipart so the first images upload with the product in one request.
        const body = new FormData();
        for (const [k, value] of Object.entries(payload(v))) {
          if (value !== null) body.append(k, String(value));
        }
        for (const f of files) body.append("uploaded_images", f);
        saved = await bff<AdminProduct>("products/", { method: "POST", body });
      }
      await refreshCatalog(saved.slug);
      qc.setQueryData(adminKeys.product(saved.slug), saved);
      qc.invalidateQueries({ queryKey: ["admin", "products"] });
      qc.invalidateQueries({ queryKey: adminKeys.lowStock });
      toast.success(product ? "Product saved" : "Product created");
      if (product) reset(initial(saved));
      else router.replace(`/admin/products/${saved.slug}`);
    } catch (e) {
      setFormError(applyServerErrors(e, form, "Could not save the product. Try again."));
    }
  });

  const text = (
    id: "name" | "sku" | "price" | "compare_at_price" | "stock" | "low_stock_threshold" | "tags",
    label: string,
    props: React.InputHTMLAttributes<HTMLInputElement> = {},
    opts: { hint?: string; optional?: boolean } = {},
  ) => (
    <Field id={id} label={label} hint={opts.hint} optional={opts.optional ? "optional" : undefined} error={errors[id]?.message}>
      <input
        id={id}
        className={inputClass}
        aria-invalid={!!errors[id]}
        aria-describedby={describedBy(id, !!errors[id], !!opts.hint)}
        {...props}
        {...register(id)}
      />
    </Field>
  );

  // The category <select> must have its options before the form value is applied, or the browser
  // shows (and a save would send) "No category".
  if (categories.isLoading) return <PanelSkeleton />;

  return (
    <form noValidate onSubmit={onSubmit} className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_300px]" aria-busy={formState.isSubmitting}>
      <div className="flex flex-col gap-6">
        <fieldset className="flex min-w-0 flex-col gap-4 rounded-xl border bg-card p-5">
          <legend className="px-1 font-semibold">Details</legend>
          {text("name", "Name")}
          <div className="grid gap-4 sm:grid-cols-2">
            {text("sku", "SKU", { autoCapitalize: "characters" }, { optional: true })}
            <Field id="category" label="Category" optional="optional">
              <select id="category" className={inputClass} {...register("category")}>
                <option value="">No category</option>
                {categories.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                    {c.is_active === false ? " (hidden)" : ""}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field id="description" label="Description (English)" optional="optional">
            <textarea id="description" rows={4} className={cn(inputClass, "h-auto py-2")} {...register("description")} />
          </Field>
          <Field id="description_sw" label="Description (Swahili)" optional="optional">
            <textarea id="description_sw" rows={4} className={cn(inputClass, "h-auto py-2")} {...register("description_sw")} />
          </Field>
          {text("tags", "Tags", {}, { hint: "Comma-separated search words, English and Swahili", optional: true })}
        </fieldset>

        {!product && (
          <fieldset className="flex min-w-0 flex-col gap-3 rounded-xl border bg-card p-5">
            <legend className="px-1 font-semibold">Images</legend>
            <Field id="uploaded_images" label="Upload images" hint="JPEG or PNG. You can add more, set alt text and reorder after saving.">
              <input
                id="uploaded_images"
                type="file"
                accept="image/*"
                multiple
                aria-describedby="uploaded_images-hint"
                className="text-sm file:mr-3 file:rounded-md file:border file:bg-background file:px-3 file:py-1.5"
                onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              />
            </Field>
            {files.length > 0 && (
              <p className="text-sm text-muted-foreground">
                {files.length} image{files.length === 1 ? "" : "s"} selected
              </p>
            )}
          </fieldset>
        )}
      </div>

      <div className="flex flex-col gap-6">
        <fieldset className="flex min-w-0 flex-col gap-4 rounded-xl border bg-card p-5">
          <legend className="px-1 font-semibold">Price and stock</legend>
          {text("price", "Price (TSh)", { inputMode: "decimal" })}
          {text("compare_at_price", "Compare-at price", { inputMode: "decimal" }, { hint: "Shown struck through when higher", optional: true })}
          {text("stock", "Stock", { inputMode: "numeric" })}
          {text("low_stock_threshold", "Low-stock alert at", { inputMode: "numeric" })}
          <label className="flex items-center gap-2 text-sm font-medium">
            <input type="checkbox" className="size-4 accent-primary" {...register("is_active")} />
            Active (visible in the shop)
          </label>
        </fieldset>
        <FormError message={formError} />
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={formState.isSubmitting}>
            {formState.isSubmitting && <Loader2 className="size-4 animate-spin" />}
            {product ? "Save changes" : "Create product"}
          </Button>
          {product && product.is_active && (
            <Button variant="outline" asChild>
              <Link href={`/products/${product.slug}`} target="_blank">
                View in shop
              </Link>
            </Button>
          )}
        </div>
      </div>
    </form>
  );
}
