"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { describedBy, Field, inputClass } from "@/components/shop/form-field";
import { PanelSkeleton } from "@/components/shop/skeletons";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n/client";
import { LOCALES, type Dictionary } from "@/i18n/config";
import { bff } from "@/lib/api/client";
import { applyServerErrors } from "@/lib/forms";
import type { User } from "@/lib/api/types";
import { stripPhone, toE164, TZ_PHONE } from "@/lib/phone";
import { sessionKey, useSession } from "@/lib/queries/session";

function schema(t: Dictionary) {
  return z.object({
    first_name: z.string().trim().max(150),
    last_name: z.string().trim().max(150),
    email: z.string().trim().refine((v) => !v || z.email().safeParse(v).success, t.checkout.invalidEmail),
    phone: z
      .string()
      .transform(stripPhone)
      .refine((v) => !v || TZ_PHONE.test(v), t.checkout.invalidPhone)
      .transform((v) => (v ? toE164(v) : v)),
    preferred_language: z.enum(["en", "sw"]),
  });
}
type Values = z.input<ReturnType<typeof schema>>;
type Parsed = z.output<ReturnType<typeof schema>>;
type TextField = "first_name" | "last_name" | "email" | "phone";

export function ProfileForm() {
  const { t } = useT();
  const qc = useQueryClient();
  const { data: user, isLoading } = useSession();
  const [formError, setFormError] = useState<string | null>(null);
  const resolver = useMemo(() => zodResolver(schema(t)), [t]);
  const { register, handleSubmit, formState, reset, setError, getValues } = useForm<Values, unknown, Parsed>({
    resolver,
    defaultValues: { first_name: "", last_name: "", email: "", phone: "", preferred_language: "en" },
  });
  const errors = formState.errors;

  useEffect(() => {
    if (!user) return;
    reset({
      first_name: user.first_name ?? "",
      last_name: user.last_name ?? "",
      email: user.email ?? "",
      phone: user.phone ?? "",
      preferred_language: user.preferred_language ?? "en",
    });
  }, [user, reset]);

  if (isLoading || !user) return <PanelSkeleton />;

  const onSubmit = handleSubmit(async (v) => {
    setFormError(null);
    try {
      const updated = await bff<User>("auth/me/", { method: "PATCH", json: { ...v, phone: v.phone || null } });
      qc.setQueryData(sessionKey, updated);
      toast.success(t.account.profileSaved);
    } catch (e) {
      setFormError(applyServerErrors(e, { getValues, setError }, t.common.errorBody));
    }
  });

  const text = (id: TextField, label: string, props: React.InputHTMLAttributes<HTMLInputElement>, hint?: string) => (
    <Field id={id} label={label} hint={hint} optional={t.common.optional} error={errors[id]?.message}>
      <input
        id={id}
        className={inputClass}
        aria-invalid={!!errors[id]}
        aria-describedby={describedBy(id, !!errors[id], !!hint)}
        {...props}
        {...register(id)}
      />
    </Field>
  );

  return (
    <form noValidate onSubmit={onSubmit} className="flex max-w-xl flex-col gap-4" aria-busy={formState.isSubmitting}>
      <div className="grid gap-4 sm:grid-cols-2">
        {text("first_name", t.auth.firstName, { autoComplete: "given-name" })}
        {text("last_name", t.auth.lastName, { autoComplete: "family-name" })}
      </div>
      {text("email", t.auth.email, { type: "email", autoComplete: "email" })}
      {text("phone", t.auth.phone, { type: "tel", inputMode: "tel", autoComplete: "tel" }, t.checkout.phoneHint)}
      <Field id="preferred_language" label={t.auth.preferredLanguage}>
        <select id="preferred_language" className={inputClass} {...register("preferred_language")}>
          {LOCALES.map((l) => (
            <option key={l} value={l}>
              {t.languages[l]}
            </option>
          ))}
        </select>
      </Field>
      {formError && (
        <p role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {formError}
        </p>
      )}
      <div>
        <Button type="submit" disabled={formState.isSubmitting}>
          {formState.isSubmitting && <Loader2 className="size-4 animate-spin" />}
          {t.common.save}
        </Button>
      </div>
    </form>
  );
}
