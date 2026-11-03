"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { describedBy, Field, inputClass } from "@/components/shop/form-field";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n/client";
import { LOCALES, type Dictionary } from "@/i18n/config";
import { ApiError } from "@/lib/api/errors";
import type { User } from "@/lib/api/types";
import { stripPhone, toE164, TZ_PHONE } from "@/lib/phone";
import { useLogin, useRegister } from "@/lib/queries/session";

function landing(next: string | null, user: User | null | undefined) {
  if (next) return next;
  return user?.role === "admin" ? "/admin" : "/account";
}

function withNext(path: string, next: string | null) {
  return next ? `${path}?next=${encodeURIComponent(next)}` : path;
}

function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
      {message}
    </p>
  );
}

function Shell({ title, children, footer }: { title: string; children: React.ReactNode; footer: React.ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-sm py-6">
      <h1 className="mb-6 text-2xl font-semibold">{title}</h1>
      {children}
      <p className="mt-6 text-center text-sm text-muted-foreground">{footer}</p>
    </div>
  );
}

export function LoginForm({ next }: { next: string | null }) {
  const { t } = useT();
  const router = useRouter();
  const login = useLogin();
  const [error, setError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm({ defaultValues: { username: "", password: "" } });

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    if (!values.username.trim() || !values.password) {
      setError(t.auth.invalid);
      return;
    }
    try {
      const body = (await login.mutateAsync({ username: values.username.trim(), password: values.password })) as {
        user?: User | null;
      };
      router.replace(landing(next, body?.user));
      router.refresh();
    } catch (e) {
      // One generic message whatever went wrong with the credentials (FR-013).
      setError(e instanceof ApiError && e.status >= 500 ? t.common.errorBody : t.auth.invalid);
    }
  });

  return (
    <Shell
      title={t.auth.loginTitle}
      footer={
        <>
          {t.auth.noAccount}{" "}
          <Link className="font-medium text-primary underline-offset-4 hover:underline" href={withNext("/register", next)}>
            {t.nav.register}
          </Link>
        </>
      }
    >
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4" aria-busy={formState.isSubmitting}>
        <Field id="username" label={t.auth.username}>
          <input id="username" autoComplete="username" autoCapitalize="none" className={inputClass} {...register("username")} />
        </Field>
        <Field id="password" label={t.auth.password}>
          <input id="password" type="password" autoComplete="current-password" className={inputClass} {...register("password")} />
        </Field>
        <FormError message={error} />
        <Button type="submit" size="lg" disabled={formState.isSubmitting}>
          {formState.isSubmitting && <Loader2 className="size-4 animate-spin" />}
          {t.auth.loginButton}
        </Button>
      </form>
    </Shell>
  );
}

function registerSchema(t: Dictionary) {
  return z.object({
    username: z.string().trim().min(1, t.checkout.required).max(150),
    password: z.string().min(8, t.auth.passwordShort),
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
type RegisterValues = z.input<ReturnType<typeof registerSchema>>;
type RegisterParsed = z.output<ReturnType<typeof registerSchema>>;

export function RegisterForm({ next }: { next: string | null }) {
  const { t, locale } = useT();
  const router = useRouter();
  const signup = useRegister();
  const [error, setFormError] = useState<string | null>(null);
  const resolver = useMemo(() => zodResolver(registerSchema(t)), [t]);
  const { register, handleSubmit, formState, setError, getValues } = useForm<RegisterValues, unknown, RegisterParsed>({
    resolver,
    defaultValues: {
      username: "",
      password: "",
      first_name: "",
      last_name: "",
      email: "",
      phone: "",
      preferred_language: locale,
    },
  });
  const errors = formState.errors;

  const onSubmit = handleSubmit(async (v) => {
    setFormError(null);
    const body: Record<string, string> = { username: v.username, password: v.password, preferred_language: v.preferred_language };
    for (const key of ["first_name", "last_name", "email", "phone"] as const) if (v[key]) body[key] = v[key];
    try {
      const res = (await signup.mutateAsync(body)) as { user?: User | null };
      router.replace(landing(next, res?.user));
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError) {
        let mapped = false;
        for (const [field, messages] of Object.entries(e.fields ?? {})) {
          if (field in getValues()) {
            setError(field as keyof RegisterValues, { message: messages[0] });
            mapped = true;
          }
        }
        if (!mapped) setFormError(e.detail ?? t.common.errorBody);
      } else {
        setFormError(t.common.errorBody);
      }
    }
  });

  const text = (
    id: "username" | "first_name" | "last_name" | "email" | "phone" | "password",
    label: string,
    props: React.InputHTMLAttributes<HTMLInputElement>,
    opts: { hint?: string; optional?: boolean } = {},
  ) => (
    <Field id={id} label={label} hint={opts.hint} optional={opts.optional ? t.common.optional : undefined} error={errors[id]?.message}>
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

  return (
    <Shell
      title={t.auth.registerTitle}
      footer={
        <>
          {t.auth.haveAccount}{" "}
          <Link className="font-medium text-primary underline-offset-4 hover:underline" href={withNext("/login", next)}>
            {t.nav.login}
          </Link>
        </>
      }
    >
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4" aria-busy={formState.isSubmitting}>
        {text("username", t.auth.username, { autoComplete: "username", autoCapitalize: "none" })}
        {text("password", t.auth.password, { type: "password", autoComplete: "new-password" }, { hint: t.auth.passwordHint })}
        <div className="grid gap-4 sm:grid-cols-2">
          {text("first_name", t.auth.firstName, { autoComplete: "given-name" }, { optional: true })}
          {text("last_name", t.auth.lastName, { autoComplete: "family-name" }, { optional: true })}
        </div>
        {text("email", t.auth.email, { type: "email", autoComplete: "email" }, { optional: true })}
        {text("phone", t.auth.phone, { type: "tel", inputMode: "tel", autoComplete: "tel" }, { hint: t.checkout.phoneHint, optional: true })}
        <Field id="preferred_language" label={t.auth.preferredLanguage}>
          <select id="preferred_language" className={inputClass} {...register("preferred_language")}>
            {LOCALES.map((l) => (
              <option key={l} value={l}>
                {t.languages[l]}
              </option>
            ))}
          </select>
        </Field>
        <FormError message={error} />
        <Button type="submit" size="lg" disabled={formState.isSubmitting}>
          {formState.isSubmitting && <Loader2 className="size-4 animate-spin" />}
          {t.auth.registerButton}
        </Button>
      </form>
    </Shell>
  );
}
