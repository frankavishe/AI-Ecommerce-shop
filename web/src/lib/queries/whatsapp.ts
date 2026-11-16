"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { bff } from "@/lib/api/client";
import type { WhatsAppLink, WhatsAppLinkCode } from "@/lib/api/types";

export const whatsappLinkKey = ["whatsapp-link"] as const;

/** The account's WhatsApp link. While a code is shown (`poll`), re-check every 5 s so the card
 * flips to "linked" as soon as the shopper sends the code (contracts/link-api.md). */
export function useWhatsAppLink({ poll = false }: { poll?: boolean } = {}) {
  return useQuery({
    queryKey: whatsappLinkKey,
    queryFn: () => bff<WhatsAppLink>("whatsapp/link/"),
    refetchInterval: poll ? 5_000 : false,
    refetchIntervalInBackground: false,
  });
}

export function useCreateLinkCode() {
  return useMutation({
    mutationFn: () => bff<WhatsAppLinkCode>("whatsapp/link/code/", { method: "POST" }),
  });
}

export function useUnlink() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => bff<void>("whatsapp/link/", { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: whatsappLinkKey }),
  });
}
