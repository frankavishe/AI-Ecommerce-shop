"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toApiError } from "@/lib/api/errors";
import type { User } from "@/lib/api/types";
import { cartKey } from "./cart";

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

async function post(path: string, json?: unknown) {
  const res = await fetch(path, {
    method: "POST",
    headers: json === undefined ? undefined : { "content-type": "application/json" },
    body: json === undefined ? undefined : JSON.stringify(json),
  });
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw toApiError(res.status, body);
  return body;
}

/** Login/register set the session cookies and merge the guest cart, so both caches are refetched. */
function useSessionMutation<V>(path: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (values: V) => post(path, values),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: sessionKey }),
        qc.invalidateQueries({ queryKey: cartKey }),
      ]);
    },
  });
}

export const useLogin = () => useSessionMutation<{ username: string; password: string }>("/api/session/login");
export const useRegister = () => useSessionMutation<Record<string, string>>("/api/session/register");

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post("/api/session/logout"),
    onSuccess: () => {
      qc.clear();
      qc.setQueryData(sessionKey, null);
    },
  });
}
