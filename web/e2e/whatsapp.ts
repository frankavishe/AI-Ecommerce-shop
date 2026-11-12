import { createHmac } from "node:crypto";
import { expect } from "@playwright/test";
import { DJANGO } from "./helpers";

export const WA_SECRET = "e2e-wa-secret";
export const WA_NUMBER_ID = "e2e-number";

/** A fresh shopper number for each test, so earlier runs never collide. */
export const uniqWaId = () => `2557${String(Date.now()).slice(-8)}`;

/** Sends a shopper's text to the e2e Django exactly like Meta would: a signed webhook POST. */
export async function sendWhatsAppText(waId: string, body: string) {
  const payload = {
    object: "whatsapp_business_account",
    entry: [
      {
        id: "WABA_ID",
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: { display_phone_number: "255700000000", phone_number_id: WA_NUMBER_ID },
              contacts: [{ profile: { name: "E2E Shopper" }, wa_id: waId }],
              messages: [
                {
                  from: waId,
                  id: `wamid.E2E${Date.now()}${Math.floor(Math.random() * 1000)}`,
                  timestamp: String(Math.floor(Date.now() / 1000)),
                  type: "text",
                  text: { body },
                },
              ],
            },
          },
        ],
      },
    ],
  };
  const raw = JSON.stringify(payload);
  const signature = "sha256=" + createHmac("sha256", WA_SECRET).update(raw).digest("hex");
  const res = await fetch(`${DJANGO}/api/whatsapp/webhook/`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-hub-signature-256": signature },
    body: raw,
  });
  expect(res.status).toBe(200);
}
