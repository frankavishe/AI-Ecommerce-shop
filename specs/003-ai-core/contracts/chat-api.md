# Contract: AI HTTP API

All endpoints are under `/api/ai/` and must appear in the drf-spectacular schema (Constitution VII).
Error bodies follow the existing shape `{"detail": "...", "code": "..."}`.

## POST /api/ai/chat/

Auth: optional JWT. Without it, the shopper is a guest. Throttles: `ai_chat` 20/min per user/IP,
10/min per conversation. Content type: `multipart/form-data` or `application/json` (text only).

Request fields:

| Field | Type | Rules |
|---|---|---|
| `message` | string | 1–2,000 characters; optional only when `image` is sent |
| `image` | file | optional; JPEG/PNG/WebP, ≤ 10 MB |
| `conversation` | string | the token from an earlier reply; omit it to start a new conversation |
| `language` | `sw` \| `en` | optional hint; otherwise detected |

Response `200`:

```json
{
  "conversation_token": "…",
  "cart_token": "…",              // guest only; usable as X-Cart-Token in the shop API
  "language": "sw",
  "state": "active",              // or "needs_human"
  "reply": "Nimepata viatu hivi…",
  "products": [                   // server-built from tool results; never from model text
    {"id": 12, "name": "Red Sneakers", "slug": "red-sneakers", "price": "45000.00",
     "compare_at_price": null, "in_stock": true, "image": "https://…/a.png", "category_name": "Shoes"}
  ],
  "cart": null,                   // or the CartSerializer shape from the shop API when a cart tool ran
  "order": null,                  // or {"number", "status", "total", "currency"}
  "payment": null,                // or {"method", "status", "checkout_link", "message"}
  "error": null                   // "model_unavailable" | "step_limit" | "timeout" with a fallback reply
}
```

Errors: `400` validation (empty message without an image, too long, bad image type or size), `404`
unknown, expired or foreign conversation token (no detail about which), `429` throttled. When the
model is down, the API still returns `200` with `error="model_unavailable"` and a localised
fallback reply (SC-008).

When `state == "needs_human"`, the message is stored and `reply` is the fixed handoff notice. No
model call is made.

## Admin: knowledge documents (role admin; others get 403)

- `GET /api/ai/admin/knowledge/`: paginated `{id, title, language, status, error, chunk_count,
  created_at, indexed_at}`.
- `POST /api/ai/admin/knowledge/` (multipart `file`, `title?`, `language?`) → `201` with
  `status="processing"`. `400` for unsupported type or a file over 10 MB.
- `GET /api/ai/admin/knowledge/{id}/` · `DELETE /api/ai/admin/knowledge/{id}/` → `204`.
- `POST /api/ai/admin/knowledge/{id}/reindex/` → `202`.

## Admin: index status and full reindex

- `GET /api/ai/admin/index-status/` → `{"products": {"ready", "pending", "failed"},
  "images": {…}, "knowledge": {…}, "failures": [{"kind", "id", "name", "error"}]}`
- `POST /api/ai/admin/reindex/` body `{"products": true, "knowledge": true, "force": false}` → `202`.

## Admin: conversations (handoff)

- `GET /api/ai/admin/conversations/?state=needs_human` → paginated `{id, state, language,
  handoff_reason, user, updated_at, last_message}`.
- `GET /api/ai/admin/conversations/{id}/` → the conversation with its messages (text, image URL,
  tool_calls).
- `POST /api/ai/admin/conversations/{id}/release/` → `200`, `state="active"`.
