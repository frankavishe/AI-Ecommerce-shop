"use client";

import { HomeButton, StatusPage } from "@/components/shop/status-page";
import { useT } from "@/i18n/client";

export default function NotFound() {
  const { t } = useT();
  return (
    <StatusPage code="404" title={t.common.notFoundTitle} body={t.common.notFoundBody} action={<HomeButton label={t.common.goHome} />} />
  );
}
