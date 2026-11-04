import Link from "next/link";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";

export function StatusPage({
  code,
  title,
  body,
  action,
}: {
  code?: string;
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <main className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center gap-4 px-4 py-16 text-center">
      {code && <p className="text-sm font-semibold tracking-widest text-primary">{code}</p>}
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="text-muted-foreground">{body}</p>
      {action}
    </main>
  );
}

export function HomeButton({ label }: { label: string }) {
  return (
    <Button asChild>
      <Link href="/">{label}</Link>
    </Button>
  );
}
