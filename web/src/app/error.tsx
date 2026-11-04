"use client";

import { Button } from "@/components/ui/button";
import { StatusPage } from "@/components/shop/status-page";
import { useT } from "@/i18n/client";

export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const { t } = useT();
  return (
    <StatusPage
      title={t.common.errorTitle}
      body={t.common.errorBody}
      action={<Button onClick={reset}>{t.common.retry}</Button>}
    />
  );
}
