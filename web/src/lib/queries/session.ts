"use client";

import { useQuery } from "@tanstack/react-query";
import type { User } from "@/lib/api/types";

export const sessionKey = ["session"] as const;

export function useSession() {
  return useQuery({
    queryKey: sessionKey,
    queryFn: async () => {
      const res = await fetch("/api/session", { cache: "no-store" });
      const data = (await res.json().catch(() => ({ user: null }))) as { user: User | null };
      return data.user ?? null;
    },
    staleTime: 60_000,
  });
}
