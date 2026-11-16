# Data Model: WhatsApp Shopping Channel (004)

There is a new Django app, `backend/apps/whatsapp`, and it adds the tables below. The changes to
existing apps are small and listed at the end. All timestamps are timezone-aware. Phones are E.164.
Money is never stored here: it is always read from `orders.Order` and `catalog.Product`.

## WhatsAppContact

One row per WhatsApp number that has written to the shop.

| Field | Type | Notes |
|---|---|---|
| id | bigint PK | |
| wa_id | char(20), unique | Number as sent by WhatsApp (digits, e.g. `255742000331`) |
| phone | char(16), unique | E.164 (`+255742000331`), via `orders.services.normalize_phone` |
| profile_name | char(120) | From `contacts[].profile.name`; display only, never trusted |
| user | FK accounts.User, null, unique, SET_NULL | Linked account (FR-008). One number per account |
| linked_at | datetime, null | |
| conversation | FK ai.Conversation, null, SET_NULL | Current conversation (FR-007). Replaced on reset (FR-007a) |
| language | char(2) `sw`/`en`, default `sw` | Copied from the conversation after each turn. Used for templates and fixed texts |
| updates_allowed | bool, default true | False after STOP/acha (FR-021) |
| last_inbound_at | datetime, null | WhatsApp timestamp of the shopper's latest message. Used for the 24 h window and the 7-day reset |
| slowdown_notice_at | datetime, null | When the last "please slow down" note was sent (FR-019) |
| created_at / updated_at | datetime | |

**Rules**:

- The 24-hour window is open while `now - last_inbound_at < 24h`.
- `last_inbound_at` only moves forward. A delayed old message never moves it back.

## WhatsAppInboundMessage

One row per message received (FR-004).

| Field | Type | Notes |
|---|---|---|
| id | bigint PK | |
| wa_message_id | char(128), **unique** | `messages[].id` (wamid…) |
| contact | FK WhatsAppContact, CASCADE | |
| type | char(16) | `text`, `image`, `audio`, `button`, `unsupported` (video, document, sticker, location, contacts, reaction, …) |
| raw_type | char(32) | WhatsApp's own type string |
| sent_at | datetime | From `timestamp`. Ordering key (FR-005) |
| received_at | datetime, auto | Used by the rate-limit counts |
| text | text | Body, caption, or the button title |
| button_id | char(256), blank | Interactive reply id (`confirm:<id>` / `change:<id>`) |
| media_id | char(128), blank | WhatsApp media id |
| media_mime | char(64), blank | |
| media | FileField, null | Downloaded audio (images go to `ChatMessage.image`). Purged after 30 days |
| transcript | text, blank | Voice transcript (FR-013) |
| transcript_language | char(8), blank | |
| duration_s | float, null | From the speech model |
| status | char(16) | See state machine below |
| error | char(64), blank | e.g. `media_download_failed`, `too_long`, `speech_unavailable`, `model_unavailable` |
| chat_message | FK ai.ChatMessage, null, SET_NULL | The user turn it became |
| processed_at | datetime, null | |

**Indexes**: `(contact, status, sent_at, id)`, `(contact, received_at)`.

**Status machine**:

```
received ──► processing ──► answered        (assistant reply sent or queued)
   │                   ├──► recorded        (saved only: needs_human, STOP/START, link code, over-24h-old, ignored)
   │                   ├──► rejected        (unsupported type, bad media, voice too long/empty)
   │                   └──► failed          (model/speech down → fallback sent; error set)
   └──► rate_limited                        (FR-019: saved, not answered)
```

A row that is `processing` when the worker crashes goes back to `received`. This happens the next
time the advisory lock is taken: rows stuck in `processing` for longer than
`AI_CHAT_TIMEOUT + 120 s` are reset.

## WhatsAppOutboundMessage

One row per message the shop sends (FR-018).

| Field | Type | Notes |
|---|---|---|
| id | bigint PK | |
| contact | FK WhatsAppContact, CASCADE | |
| conversation | FK ai.Conversation, null, SET_NULL | |
| kind | char(16) | `text`, `image`, `buttons`, `template` |
| trigger | char(16) | `assistant`, `staff`, `system` (fallbacks, notes, link replies), `order_update`, `payment` |
| body | JSON | The exact Graph `messages` payload, without the token |
| text | text | Human-readable copy for the history |
| batch | UUID | Messages of one reply, sent in order |
| position | smallint | Order within the batch |
| wa_message_id | char(128), unique, null | Set after a successful send |
| status | char(12) | `queued`, `sent`, `delivered`, `read`, `failed`, `skipped` (window closed or batch aborted) |
| status_at | datetime, null | |
| attempts | smallint, default 0 | |
| error_code | char(16), blank | Graph error code |
| error | text, blank | |
| staff_user | FK User, null, SET_NULL | For staff replies |
| created_at | datetime | |

**Rules**:

- Status only moves forward, in the order `queued < sent < delivered < read`. `failed` and
  `skipped` are final.
- Status callbacks for an unknown `wa_message_id` are logged and ignored.

## WhatsAppOrder

The order was placed from a WhatsApp conversation (R5).

| Field | Type | Notes |
|---|---|---|
| order | OneToOne orders.Order, PK, CASCADE | |
| contact | FK WhatsAppContact, CASCADE, related `orders` | |
| created_at | datetime | |

This table drives FR-009 (`phone_orders`) and FR-021 (only these orders get updates).

## WhatsAppOrderNotification

One row per order update sent (FR-021, SC-002).

| Field | Type | Notes |
|---|---|---|
| id | bigint PK | |
| order | FK orders.Order, CASCADE | |
| status | char(20) | `paid`, `out_for_delivery`, `delivered`, `cancelled`, `expired` |
| outbound | FK WhatsAppOutboundMessage, null, SET_NULL | |
| state | char(10) | `sending`, `sent`, `failed`, `skipped` (updates off) |
| created_at | datetime | |

**Constraint**: unique `(order, status)`.

## WhatsAppCheckoutPrompt

One Confirm / Change button message (FR-016a, R6).

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | Goes into the button ids |
| conversation | FK ai.Conversation, CASCADE | |
| contact | FK WhatsAppContact, CASCADE | |
| fingerprint | char(64) | sha256 of the cart lines, details, method, network, fee and total |
| method | char(16) | `mobile_money` / `card` |
| network | char(16), blank | |
| total | Decimal(12,2) | Shown in the button body only. Never used to charge |
| order | FK orders.Order, null, SET_NULL | Set when Confirm placed it. A repeat tap resends the payment message |
| created_at | datetime | |

**Valid Confirm**:

- The prompt is the newest for its conversation.
- `created_at` is within 10 minutes.
- The fingerprint equals the recomputed one.
- `order` is null.

## WhatsAppLinkCode

A one-time code for linking an account (FR-008).

| Field | Type | Notes |
|---|---|---|
| id | bigint PK | |
| user | FK accounts.User, CASCADE | |
| code_hash | char(64), unique | sha256 of the uppercased code |
| expires_at | datetime | created + 10 min |
| used_at | datetime, null | |
| used_by | FK WhatsAppContact, null, SET_NULL | |
| created_at | datetime | |

**Rules**:

- Issuing a new code expires the user's unused codes.
- A code is valid when it is unused, `expires_at > now`, and no newer code was issued.
- Wrong attempts are counted in `WhatsAppLinkAttempt(contact, created_at)`. At most 5 per hour.

## WhatsAppMediaUpload

A cache of product photos already uploaded to WhatsApp (R7).

| Field | Type | Notes |
|---|---|---|
| product_image | OneToOne catalog.ProductImage, PK, CASCADE | |
| media_id | char(128) | |
| uploaded_at | datetime | Reused while it is younger than 25 days |

## Changes to existing apps

| App | Change | Migration |
|---|---|---|
| `ai.ChatMessage` | `Role.STAFF = "staff"` (staff replies, US4) | choices only |
| `ai.ChatMessage.payload` | User turns from WhatsApp carry `{"whatsapp": {"type", "wa_message_id", "transcript"?}}` | none (JSON) |
| `ai.Conversation` | No schema change. `channel="whatsapp"` already exists | none |
| `ai.tools.ToolContext` | `verified_phone`, `phone_orders`, `checkout_summary` | code only |
| `ai.agent` | `handle_message(..., verified_phone, phone_orders, meta, record_only)`. `AgentReply.summary`, `AgentReply.incoming` | code only |
| `ai.tasks.purge_old_conversations` | Also deletes `WhatsAppInboundMessage.media` files older than 30 days | none |
| `accounts.User.whatsapp_verified` | Already exists. Set or cleared on link and unlink | none |

## Relationships

```
accounts.User 1 ─── 0..1 WhatsAppContact ─── 0..1 ai.Conversation (current)
WhatsAppContact 1 ─── * WhatsAppInboundMessage ─── 0..1 ai.ChatMessage
WhatsAppContact 1 ─── * WhatsAppOutboundMessage
WhatsAppContact 1 ─── * WhatsAppOrder 1 ─── 1 orders.Order 1 ─── * WhatsAppOrderNotification
ai.Conversation 1 ─── * WhatsAppCheckoutPrompt ─── 0..1 orders.Order
accounts.User 1 ─── * WhatsAppLinkCode
catalog.ProductImage 1 ─── 0..1 WhatsAppMediaUpload
```
