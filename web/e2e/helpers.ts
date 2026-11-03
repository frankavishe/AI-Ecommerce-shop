import { expect, type Page } from "@playwright/test";

export const FAKE_STAKABA = "http://127.0.0.1:8765";
export const DJANGO = "http://127.0.0.1:8001";
export const WEBHOOK_TOKEN = "e2e-webhook-token";
export const PASSWORD = "e2e-pass-123";

export async function login(page: Page, username: string, password = PASSWORD) {
  await page.goto("/login");
  await page.getByLabel(/username|jina la mtumiaji/i).fill(username);
  await page.getByLabel(/^password$|^nenosiri$/i).fill(password);
  await page.getByRole("button", { name: /^log in$|^ingia$/i }).click();
}

/** Simulates Stakaba confirming the latest payment for an order (POSTs the token-URL webhook). */
export async function simulatePayment(orderNumber: string, status = "SUCCESS") {
  const list = (await (await fetch(`${FAKE_STAKABA}/_e2e/payments`)).json()) as {
    internalReference: string;
    orderId: string;
    grossAmount: number;
  }[];
  const payment = list.filter((p) => p.orderId?.startsWith(orderNumber)).at(-1);
  expect(payment, `no fake payment for ${orderNumber}`).toBeTruthy();
  const res = await fetch(`${DJANGO}/api/payments/stakaba/webhook/${WEBHOOK_TOKEN}/`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      internalReference: payment!.internalReference,
      status,
      grossAmount: payment!.grossAmount,
      currency: "TZS",
      metadata: { orderId: payment!.orderId },
    }),
  });
  expect(res.status).toBe(200);
}

/** Empties the browser's cart through the BFF so each test starts clean. */
export async function clearCart(page: Page) {
  await page.request.delete("/bff/api/cart/");
}

export function orderNumberFromUrl(url: string) {
  const m = /\/orders\/([A-Z0-9]+)/.exec(url);
  if (!m) throw new Error(`not an order URL: ${url}`);
  return m[1];
}
