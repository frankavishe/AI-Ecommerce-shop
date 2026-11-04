"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Toaster } from "@/components/ui/sonner";
import { I18nProvider } from "@/i18n/client";
import type { Locale } from "@/i18n/config";
import { ApiError } from "@/lib/api/errors";

export function Providers({ locale, children }: { locale: Locale; children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            // Client errors (4xx) won't fix themselves; retry only network/5xx once.
            retry: (count, error) => count < 1 && !(error instanceof ApiError && error.status < 500),
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <I18nProvider locale={locale}>
        {children}
        <Toaster position="top-center" richColors />
      </I18nProvider>
    </QueryClientProvider>
  );
}
