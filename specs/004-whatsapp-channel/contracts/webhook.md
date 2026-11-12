# Contract: WhatsApp Webhook (inbound from Meta)

Base path: `/api/whatsapp/webhook/`. This endpoint is public and has no session or JWT. It is
excluded from DRF authentication, throttling and CSRF. It appears in the OpenAPI schema with the
tag `whatsapp-webhook`.

## GET — subscription handshake (FR-001)

Query: `hub.mode`, `hub.verify_token`, `hub.challenge`.

| Condition | Response |
|---|---|
| `hub.mode == "subscribe"` and `hub.verify_token` equals `WHATSAPP_VERIFY_TOKEN` (constant-time) | `200 text/plain`, body = `hub.challenge` exactly |
| anything else, including an empty configured token | `403`, empty body |

## POST — notifications (FR-002 … FR-006)

Headers: `X-Hub-Signature-256: sha256=<hex>`, `Content-Type: application/json`.

1. Compute `HMAC-SHA256(WHATSAPP_APP_SECRET, raw request body)`. If the header is missing,
   malformed or doesn't match, return **403**. Nothing is parsed, stored or queued (SC-001).
2. If the body is not JSON or `object != "whatsapp_business_account"`, return **200** and ignore
   it (logged).
3. For each `entry[].changes[]` with `field == "messages"`:
   - If `value.metadata.phone_number_id != WHATSAPP_PHONE_NUMBER_ID`, skip it (edge case: another
     business number).
   - `value.contacts[]` updates or creates `WhatsAppContact` (`wa_id`, `profile.name`).
   - `value.messages[]` runs
     `get_or_create(wa_message_id=id)` → if created, queue `drain_contact(contact_id)` on commit.
   - `value.statuses[]` updates `WhatsAppOutboundMessage` by `id` (forward-only). `failed` stores
     `errors[0].code/title`.
4. Return **200** `{"ok": true}` within the request, with no network calls in the request path.

### Inbound message mapping

| WhatsApp `type` | Stored `type` | Fields used |
|---|---|---|
| `text` | `text` | `text.body` |
| `image` | `image` | `image.id`, `image.mime_type`, `image.caption` |
| `audio` (incl. `voice: true`) | `audio` | `audio.id`, `audio.mime_type` |
| `interactive` with `interactive.type == "button_reply"` | `button` | `button_reply.id` → `button_id`, `button_reply.title` → `text` |
| `button` (template quick reply) | `text` | `button.text` |
| `video`, `document`, `sticker`, `location`, `contacts`, `reaction`, `order`, `system`, `unknown`, `interactive` of other kinds | `unsupported` | `raw_type` |

`timestamp` (unix seconds) → `sent_at`. `from` → the contact's `wa_id`.

### Example (text)

```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "WABA_ID",
    "changes": [{
      "field": "messages",
      "value": {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "255700000000", "phone_number_id": "PHONE_NUMBER_ID"},
        "contacts": [{"profile": {"name": "Asha"}, "wa_id": "255742000331"}],
        "messages": [{
          "from": "255742000331", "id": "wamid.HBgM...", "timestamp": "1762934400",
          "type": "text", "text": {"body": "nataka viatu vyekundu"}
        }]
      }
    }]
  }]
}
```

### Example (button reply)

```json
{"from": "255742000331", "id": "wamid.X", "timestamp": "1762934460", "type": "interactive",
 "interactive": {"type": "button_reply",
                 "button_reply": {"id": "confirm:3f2a…", "title": "Thibitisha"}}}
```

## Processing pipeline (the `drain_contact` task, per number, in order)

The steps for each `received` row, ordered by `(sent_at, id)`, under the contact's advisory lock:

1. **Window and age**: update `contact.last_inbound_at` (forward only). If `sent_at` is more than
   24 h before now, set `recorded` (save only).
2. **Rate limit** (R11): if over the limit, set `rate_limited`, save the message, and send at most
   one slow-down note per window.
3. **Reset** (R12): start a new conversation after 7 days of silence (not when `needs_human`).
4. **Control words**: STOP/acha/sitaki/unsubscribe and START/anza toggle `updates_allowed`. A
   link code (`LINK-XXXXXX`) is handled as in [link-api.md](link-api.md). These are not sent to
   the assistant.
5. **Needs human**: save the message (`record_only`) and send nothing (US4-1).
6. **By type**:
   - `text`: `handle_message(text)`
   - `image`: download → validate (JPEG/PNG/WebP, ≤ 10 MB) → `handle_message(text=caption,
     image=file)`. On failure, the shopper gets "type not supported" or "please resend".
   - `audio`: download (≤ 2 MB) → `clients.transcribe` → too long or empty → "type or send a
     shorter note". Otherwise `handle_message(text=transcript, language=sw|en)`, and the reply is
     prefixed with the "heard" line.
   - `button`: `confirm:<id>` / `change:<id>`, as in research R6. An unknown or foreign prompt id
     gets "this button has expired" plus a fresh summary if a cart exists.
   - `unsupported`: the "here's what I can handle" text.
7. **Send** (as described in [outbound.md](outbound.md)):
   - the reply text, split into chunks
   - product photos, at most 3
   - the payment message if there is an order or payment
   - Confirm/Change buttons if there is a summary

   The window is checked first.
8. Link a `WhatsAppOrder` if `conversation.last_order` changed. Copy `conversation.language` to
   the contact. Set the status and `processed_at`.

Any `ModelUnavailable` from speech or images, and the agent's own fallback, all end with a fallback
text sent and `status=failed, error=…` (FR-020, SC-008).
