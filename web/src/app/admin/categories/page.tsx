"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { refreshCatalog } from "@/app/admin/actions";
import { EmptyRow, ErrorState, FormError, PageHeader, tableWrap, td, th } from "@/components/admin/ui";
import { describedBy, Field, inputClass } from "@/components/shop/form-field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { bff } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Category } from "@/lib/api/types";
import { applyServerErrors } from "@/lib/forms";
import { adminKeys, useAdminCategories } from "@/lib/queries/admin";

const schema = z.object({
  name: z.string().trim().min(1, "Name is required.").max(120),
  name_sw: z.string().trim().max(120),
  parent: z.string(),
  is_active: z.boolean(),
});
type Values = z.infer<typeof schema>;

function CategoryDialog({
  category,
  categories,
  open,
  onOpenChange,
}: {
  category: Category | null;
  categories: Category[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const qc = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: category?.name ?? "",
      name_sw: category?.name_sw ?? "",
      parent: category?.parent ? String(category.parent) : "",
      is_active: category?.is_active ?? true,
    },
  });
  const { register, handleSubmit, formState } = form;
  const errors = formState.errors;

  const onSubmit = handleSubmit(async (v) => {
    setFormError(null);
    const json = { ...v, parent: v.parent ? Number(v.parent) : null };
    try {
      await bff<Category>(category ? `categories/${category.slug}/` : "categories/", {
        method: category ? "PATCH" : "POST",
        json,
      });
      await refreshCatalog();
      await qc.invalidateQueries({ queryKey: adminKeys.categories });
      toast.success("Category saved");
      onOpenChange(false);
    } catch (e) {
      setFormError(applyServerErrors(e, form, "Could not save the category. Try again."));
    }
  });

  // A category cannot be its own parent.
  const parents = categories.filter((c) => c.id !== category?.id);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{category ? "Edit category" : "New category"}</DialogTitle>
        </DialogHeader>
        <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4" aria-busy={formState.isSubmitting}>
          <Field id="cat-name" label="Name" error={errors.name?.message}>
            <input id="cat-name" className={inputClass} aria-invalid={!!errors.name} aria-describedby={describedBy("cat-name", !!errors.name)} {...register("name")} />
          </Field>
          <Field id="cat-name-sw" label="Swahili name" optional="optional">
            <input id="cat-name-sw" className={inputClass} {...register("name_sw")} />
          </Field>
          <Field id="cat-parent" label="Parent" optional="optional">
            <select id="cat-parent" className={inputClass} {...register("parent")}>
              <option value="">None (top level)</option>
              {parents.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-primary" {...register("is_active")} />
            Active (visible in the shop)
          </label>
          <FormError message={formError} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={formState.isSubmitting}>
              {formState.isSubmitting && <Loader2 className="size-4 animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DeleteButton({ category }: { category: Category }) {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const remove = useMutation({
    mutationFn: () => bff<null>(`categories/${category.slug}/`, { method: "DELETE" }),
    onSuccess: async () => {
      await refreshCatalog();
      await qc.invalidateQueries({ queryKey: adminKeys.categories });
      toast.success("Category deleted");
    },
    onError: (e) => {
      setConfirming(false);
      toast.error((e instanceof ApiError && e.detail) || "Could not delete. Hide it instead if products still use it.");
    },
  });
  if (!confirming) {
    return (
      <Button variant="ghost" size="icon" aria-label={`Delete ${category.name}`} onClick={() => setConfirming(true)}>
        <Trash2 className="size-4" />
      </Button>
    );
  }
  return (
    <span className="inline-flex gap-1">
      <Button variant="destructive" size="sm" onClick={() => remove.mutate()} disabled={remove.isPending}>
        {remove.isPending && <Loader2 className="size-4 animate-spin" />}
        Delete
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
        Keep
      </Button>
    </span>
  );
}

export default function AdminCategoriesPage() {
  const categories = useAdminCategories();
  const [editing, setEditing] = useState<Category | null>(null);
  const [open, setOpen] = useState(false);
  const [formKey, setFormKey] = useState(0);
  const list = categories.data ?? [];
  const nameOf = (id?: number | null) => list.find((c) => c.id === id)?.name ?? "—";

  const openFor = (c: Category | null) => {
    setEditing(c);
    setFormKey((k) => k + 1);
    setOpen(true);
  };

  return (
    <>
      <PageHeader
        title="Categories"
        description="Hidden categories stay attached to their products but disappear from the shop menus."
        actions={
          <Button onClick={() => openFor(null)}>
            <Plus className="size-4" />
            New category
          </Button>
        }
      />
      {categories.isError ? (
        <ErrorState onRetry={() => categories.refetch()} />
      ) : (
        <div className={tableWrap}>
          <table className="w-full min-w-[560px] text-sm">
            <thead className="border-b bg-muted/50">
              <tr>
                <th className={th}>Name</th>
                <th className={th}>Swahili</th>
                <th className={th}>Parent</th>
                <th className={th}>Status</th>
                <th className={`${th} text-right`}>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {categories.isLoading && (
                <tr>
                  <td colSpan={5} className="p-3">
                    <Skeleton className="h-8 w-full" />
                  </td>
                </tr>
              )}
              {categories.data?.length === 0 && <EmptyRow colSpan={5}>No categories yet.</EmptyRow>}
              {list.map((c) => (
                <tr key={c.id}>
                  <td className={`${td} font-medium`}>{c.name}</td>
                  <td className={`${td} text-muted-foreground`}>{c.name_sw || "—"}</td>
                  <td className={`${td} text-muted-foreground`}>{nameOf(c.parent)}</td>
                  <td className={td}>
                    {c.is_active === false ? <Badge variant="outline">Hidden</Badge> : <Badge variant="secondary">Active</Badge>}
                  </td>
                  <td className={`${td} whitespace-nowrap text-right`}>
                    <Button variant="ghost" size="icon" aria-label={`Edit ${c.name}`} onClick={() => openFor(c)}>
                      <Pencil className="size-4" />
                    </Button>
                    <DeleteButton category={c} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <CategoryDialog key={formKey} category={editing} categories={list} open={open} onOpenChange={setOpen} />
    </>
  );
}
