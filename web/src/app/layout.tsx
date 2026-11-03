import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Suspense, type ReactNode } from "react";
import { getLocale } from "@/i18n/server";
import { Providers } from "./providers";
import "./globals.css";

const geistSans = Geist({ variable: "--font-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

const shopName = process.env.NEXT_PUBLIC_SHOP_NAME ?? "Duka";

export const metadata: Metadata = {
  title: { default: shopName, template: `%s · ${shopName}` },
  description: "Shop online in Tanzania and pay with mobile money or card.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#1f6b4f" };

/** Locale comes from a cookie, so it is read at request time inside Suspense (Cache Components). */
async function LocaleRoot({ children }: { children: ReactNode }) {
  const locale = await getLocale();
  return <Providers locale={locale}>{children}</Providers>;
}

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="sw" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-background text-foreground">
        <Suspense fallback={null}>
          <LocaleRoot>{children}</LocaleRoot>
        </Suspense>
      </body>
    </html>
  );
}
