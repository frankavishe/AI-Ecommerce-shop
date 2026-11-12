# Contract: Staff tools for WhatsApp conversations (US4)

All endpoints use `IsShopAdmin`. Customers, riders and anonymous users get 403 or 401 (US4-4).

## Reused from 003, extended

`GET /api/ai/admin/conversations/?state=needs_human&channel=whatsapp`

- New query parameter `channel` (`api` | `whatsapp`).
- List items gain `whatsapp: {"number": "+255742000331", "profile_name": "Asha",
  "window_open": true, "window_closes_at": "…"} | null`.

`GET /api/ai/admin/conversations/{id}/`

- Messages now include `role: "staff"`.
- WhatsApp user turns carry `payload.whatsapp.type` (`text|image|audio|button`) and
  `payload.whatsapp.transcript` for voice notes. Images use the existing `image` URL, or
  `image_deleted`.

`POST /api/ai/admin/conversations/{id}/release/` (unchanged): the state goes back to `active`
(US4-5).

## New

### POST /api/whatsapp/admin/conversations/{id}/reply/

Request, one of:

```json
{"text": "Habari Asha, nimeangalia oda yako…"}
{"template": "follow_up"}
```

| Case | Response |
|---|---|
| Free text, window open, WhatsApp conversation | `202 {"outbound_id": 41, "status": "queued"}`. A `ChatMessage(role=staff)` is stored. The text is split and sent with `trigger=staff`, `staff_user=request.user` |
| Free text, window closed | `409 {"code": "window_closed", "detail": "The shopper's last message was more than 24 hours ago. Only the approved follow-up template can be sent.", "templates": ["follow_up"]}` (FR-024, US4-3) |
| `template: follow_up` | `202`. Sent at any time. A staff ChatMessage is stored with the template text |
| Not a WhatsApp conversation | `400 {"code": "not_whatsapp"}` |
| Empty or over 4096 × 3 characters | `400` |

A staff reply does **not** change the conversation state. Staff release it explicitly.

### GET /api/whatsapp/admin/outbound/?status=failed&contact=<id>

A paginated list of outbound messages. Use it to find failed order updates and sends (US5-5).
Fields: `id, contact_number, kind, trigger, text, status, error_code, error, attempts, created_at,
order_number|null`.

## Django admin (back office)

Read-only admins are registered for `WhatsAppContact`, `WhatsAppInboundMessage`,
`WhatsAppOutboundMessage`, `WhatsAppOrderNotification` and `WhatsAppLinkCode` (code hash hidden).
They have list filters by status and type.
