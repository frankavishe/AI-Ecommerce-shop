"use client";

import { Copy, Loader2, MessageCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useT } from "@/i18n/client";
import { fmt } from "@/i18n/config";
import { ApiError } from "@/lib/api/errors";
import type { WhatsAppLinkCode } from "@/lib/api/types";
import { formatDateTime } from "@/lib/dates";
import { useCreateLinkCode, useUnlink, useWhatsAppLink } from "@/lib/queries/whatsapp";

/** Seconds left as "m:ss" (never negative). */
export function formatCountdown(msLeft: number): string {
  const total = Math.max(0, Math.ceil(msLeft / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

export function WhatsAppLinkCard() {
  const { t, locale } = useT();
  const w = t.account.whatsapp;
  const [code, setCode] = useState<WhatsAppLinkCode | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [polling, setPolling] = useState(false);
  const link = useWhatsAppLink({ poll: polling });
  const create = useCreateLinkCode();
  const unlink = useUnlink();
  const linked = link.data?.linked ?? false;

  // A code is shown until it expires or the poll sees the link (the shopper sent it).
  const now = useNow(code !== null && !linked);
  const msLeft = code ? new Date(code.expires_at).getTime() - now : 0;
  const showingCode = code !== null && msLeft > 0 && !linked;
  if (polling !== showingCode) setPolling(showingCode);

  const getCode = () =>
    create.mutate(undefined, {
      onSuccess: setCode,
      onError: (e) => toast.error(e instanceof ApiError && e.status === 503 ? w.notConfigured : t.common.errorBody),
    });

  const copy = async () => {
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code.code);
      toast.success(w.copied);
    } catch {
      /* clipboard blocked: the code is on screen */
    }
  };

  const doUnlink = () =>
    unlink.mutate(undefined, {
      onSuccess: () => {
        setConfirming(false);
        setCode(null);
        toast.success(w.unlinked);
      },
      onError: () => toast.error(t.common.errorBody),
    });

  return (
    <section aria-labelledby="whatsapp-title" className="mt-10 max-w-xl rounded-lg border p-5" data-testid="whatsapp-card">
      <h2 id="whatsapp-title" className="flex items-center gap-2 text-lg font-semibold">
        <MessageCircle className="size-5" aria-hidden />
        {w.title}
      </h2>

      {link.isLoading ? (
        <Loader2 className="mt-4 size-5 animate-spin text-muted-foreground" aria-label={t.common.loading} />
      ) : linked && link.data ? (
        <div className="mt-3 flex flex-col gap-3 text-sm">
          <p className="font-medium">{fmt(w.linkedAs, { number: link.data.number ?? "" })}</p>
          <p className="text-muted-foreground">{fmt(w.linkedOn, { date: formatDateTime(link.data.linked_at, locale) })}</p>
          {confirming ? (
            <div className="flex flex-wrap items-center gap-2">
              <span>{w.confirmUnlink}</span>
              <Button size="sm" variant="destructive" onClick={doUnlink} disabled={unlink.isPending}>
                {unlink.isPending && <Loader2 className="size-4 animate-spin" />}
                {w.unlink}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                {w.cancel}
              </Button>
            </div>
          ) : (
            <div>
              <Button size="sm" variant="outline" onClick={() => setConfirming(true)}>
                {w.unlink}
              </Button>
            </div>
          )}
        </div>
      ) : (
        <div className="mt-3 flex flex-col gap-4 text-sm">
          <p className="text-muted-foreground">{w.explanation}</p>
          {showingCode && code ? (
            <div className="flex flex-col gap-3">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">{w.codeLabel}</p>
                <p className="font-mono text-3xl font-semibold tracking-widest" data-testid="whatsapp-code">
                  {code.code}
                </p>
                <p className="text-muted-foreground" aria-live="polite">
                  {fmt(w.expiresIn, { time: formatCountdown(msLeft) })}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button asChild size="sm">
                  <a href={code.wa_link} target="_blank" rel="noopener noreferrer">
                    <MessageCircle className="size-4" />
                    {w.openWhatsApp}
                  </a>
                </Button>
                <Button size="sm" variant="outline" onClick={copy}>
                  <Copy className="size-4" />
                  {w.copyCode}
                </Button>
              </div>
            </div>
          ) : (
            <div>
              <Button size="sm" onClick={getCode} disabled={create.isPending}>
                {create.isPending && <Loader2 className="size-4 animate-spin" />}
                {w.getCode}
              </Button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
