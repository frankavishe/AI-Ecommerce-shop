"use client";

import { HomeButton, StatusPage } from "@/components/shop/status-page";
import { useT } from "@/i18n/client";

export default function Forbidden() {
  const { t } = useT();
  return (
    <StatusPage code="403" title={t.common.forbiddenTitle} body={t.common.forbiddenBody} action={<HomeButton label={t.common.goHome} />} />
  );
}
