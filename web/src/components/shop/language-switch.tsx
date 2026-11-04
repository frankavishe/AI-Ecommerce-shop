"use client";

import { Languages } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n/client";

/** Toggles en/sw; the choice is kept in the sa_lang cookie (FR-023). */
export function LanguageSwitch() {
  const { locale, t } = useT();
  const router = useRouter();
  const [pending, start] = useTransition();
  const next = locale === "sw" ? "en" : "sw";

  return (
    <Button
      variant="ghost"
      size="sm"
      disabled={pending}
      aria-label={`${t.common.language}: ${t.languages[next]}`}
      onClick={() =>
        start(async () => {
          await fetch("/api/lang", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ lang: next }),
          });
          router.refresh();
        })
      }
    >
      <Languages className="size-4" />
      <span>{next === "sw" ? "SW" : "EN"}</span>
    </Button>
  );
}
