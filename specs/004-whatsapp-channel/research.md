# Research: WhatsApp Shopping Channel (004)

Decisions made while planning. Each one lists the decision, the reason, and the alternatives
considered.

## R1. Webhook authentication and acknowledgement

- **Decision**: `GET /api/whatsapp/webhook/` answers `hub.challenge` as plain text only when
  `hub.mode == "subscribe"` and `hub.verify_token` equals `WHATSAPP_VERIFY_TOKEN` (compared with
  `hmac.compare_digest`). Otherwise it returns 403. `POST` computes
  `"sha256=" + HMAC_SHA256(WHATSAPP_APP_SECRET, request.body)` over the **raw body**, before
  DRF parses anything, and compares it with `X-Hub-Signature-256` in constant time. On a mismatch
  or a missing header it returns 403 and stores nothing. A valid POST is parsed and its rows are
  written in one transaction. Processing is queued with `transaction.on_commit`, and the view
  returns `200` right away, even for payloads it ignores, so Meta does not retry them.
- **Rationale**: Constitution IV and FR-001 to FR-003. The signature covers the exact bytes, so the
  body must not be re-serialized. Meta retries anything that isn't 200 for up to 7 days.
- **Alternatives**: a DRF parser with a signature hook (re-encoding risk), or a secret URL token
  instead of the signature (weaker; Meta signs, so use it).

## R2. Idempotency

- **Decision**: `WhatsAppInboundMessage.wa_message_id` is unique. The webhook uses
  `get_or_create`, and only a *created* row queues work. Status callbacks update
  `WhatsAppOutboundMessage` by `wa_message_id` and only move forward
  (`sent < delivered < read`; `failed` is final). Order updates use a unique
  `(order, status)` row in `WhatsAppOrderNotification`, inserted before the send.
- **Rationale**: FR-004, FR-021, SC-002. The DB constraint holds even under concurrent retries.
- **Alternatives**: Redis "seen" keys (lost on flush, not auditable).

## R3. One-at-a-time, in-order processing per number (FR-005)

- **Decision**: the webhook queues `whatsapp.tasks.drain_contact(contact_id)`. The task takes a
  **session-level Postgres advisory lock** (`pg_try_advisory_lock(<ns>, contact_id)`). If the lock
  is held, it returns: the holder will see the new row. While it holds the lock, it repeatedly takes
  the oldest `received` message for the contact, ordered by `(sent_at, id)`, and processes it.
  After releasing the lock, it checks once more for `received` rows and loops if there are any.
  This closes the race between "nothing left" and the release.
- **Rationale**: Celery does not order tasks. A row lock would keep a DB transaction open for the
  whole model turn (up to `AI_CHAT_TIMEOUT`), and would delay the tools' commits and `on_commit`
  callbacks. An advisory lock is tied to the worker's connection, so a crashed worker frees it
  automatically. It needs no Redis, and the cache in tests is locmem.
- **Alternatives**: a Redis lock with a TTL (stale-lock tuning, and a lock-free window if the turn
  outlives the TTL), or a dedicated single-concurrency queue (serializes all numbers, not one
  number).
- A Celery `soft_time_limit` of `AI_CHAT_TIMEOUT + 60` is a safety net. The agent already stops at
  its own deadline and returns the fallback. A late answer is never sent, because sending happens
  only after `handle_message` returns.

## R4. Reusing the 003 assistant: what changes in `apps/ai`

The assistant's rules are unchanged. Five small additive hooks are needed, and each is
backward-compatible for `POST /api/ai/chat`:

1. `handle_message(..., verified_phone=None, phone_orders=None, meta=None, record_only=False)`.
   - `verified_phone` and `phone_orders` go onto `ToolContext`.
   - `meta` is stored in the user `ChatMessage.payload`, e.g. `{"whatsapp": {"type": "voice",
     "wa_message_id": ...}}`.
   - `record_only` saves the shopper message without running the model. It is used while flagged
     for a human and when rate-limited, so the staff history is complete.
2. `ToolContext.verified_phone` is the default contact phone in `prefilled()` (FR-009 "offered that
   number"). The model can still collect another phone.
3. `order_status` for a guest with `phone_orders`: without a number, it returns the latest order in
   `phone_orders`. With a number, it looks in `phone_orders` first, then falls back to the 003
   number+phone rule (FR-009, acceptance US2-4/5/6). For a customer, it uses the user's orders plus
   `phone_orders`.
4. `ToolContext.checkout_summary`: the `checkout` tool sets it when it returns a summary (the
   confirm=false path or an unseen confirm). It holds the server totals, method, network and the
   fingerprint inputs. `AgentReply` gets `summary` and `incoming` attributes, which are **not**
   added to the chat API payload.
5. `ChatMessage.Role.STAFF` is a new choice (state-only migration). `_history()` keeps sending only
   user and assistant turns to the model.

- **Rationale**: the spec says "reuse unchanged". These hooks add channel facts (a verified phone,
  orders vouched for by the channel). They don't change prices, permissions or flows. Web chat
  behaviour is identical when the new arguments are left out, and the 003 tests must stay green.
- **Alternatives**: forking `handle_message` for WhatsApp (two loops drift apart), or putting the
  phone into `checkout_details` up front (it would look shopper-provided and skip validation
  messaging).

## R5. Orders "placed from WhatsApp"

- **Decision**: `whatsapp.WhatsAppOrder(order 1:1, contact FK)`. It is created (a) after a turn,
  when `conversation.last_order_id` changed during `handle_message`, and (b) by the Confirm-button
  path. `phone_orders = Order.objects.filter(whatsapp__contact=contact)`.
- **Rationale**: the link outlives the 90-day conversation purge and number resets (FR-007a). It
  drives order updates (FR-021) and phone-verified lookup (FR-009) without touching `orders`.
- **Alternatives**: `Order.channel` or `Order.conversation` FK (changes 001 models; conversations
  are purged), or matching on `contact_phone` (the shopper may give a different delivery phone, and
  a registered user's phone ≠ proof).

## R6. Confirm / Change buttons (FR-016a)

- **Decision**:
  - When `AgentReply.summary` is set, the assistant's text goes out first. Then the server sends an
    interactive **reply-button** message: a body built from server data ("Jumla: 125,000 TZS
    (pamoja na usafirishaji 5,000). Thibitisha oda?") and two buttons:
    `confirm:<prompt_id>` and `change:<prompt_id>`. Titles are at most 20 characters
    ("Thibitisha" / "Badilisha", "Confirm" / "Change").
  - `WhatsAppCheckoutPrompt` stores the fingerprint: sha256 over sorted cart lines
    `(product_id, qty, unit price)`, the normalized checkout details, method, network, delivery fee
    and total.
  - **Confirm tap** (the processing task, already serialized per number):
    1. Lock the prompt row. If `order_id` is set, resend that order's payment message and stop
       (double tap = one order).
    2. If the prompt isn't the newest for the conversation, or is older than
       `CONFIRM_WINDOW` (10 min, same as 003), refuse.
    3. Recompute the fingerprint from the current state. If it differs, refuse. A refusal runs the
       `checkout` tool with `confirm=false` and sends a fresh summary with new buttons.
    4. Otherwise call `tools.run_tool(ctx, "checkout", {"confirm": true, "method": …,
       "network": …})` directly. This is the same server code as a typed confirm, with **no
       model**.
    5. Save `prompt.order`, link `WhatsAppOrder`, and send the payment message (R8).
  - **Change tap**: `handle_message(text="Nataka kubadilisha kitu" | "I want to change something")`.
  - A stored `ChatMessage` (role user, text "✓ Confirm" / "Change") and an assistant row with the
    result keep the history readable for the model and staff.
- **Rationale**: the 003 CPU model is unreliable at `confirm=true` (memory: "CPU gaps: order
  confirm"). Buttons make checkout deterministic and keep the typed path working.
- **Alternatives**: a WhatsApp Flows form (out of scope, needs Meta approval), or a list message
  (more taps).

## R7. Media: inbound download, outbound product photos

- **Inbound**: `GET /{media-id}` → `{url, mime_type, file_size}`, then `GET url` with the bearer
  token. Both happen in the processing task, never the webhook. The URL expires after about
  5 minutes, so it is always fetched fresh.
  - Images: JPEG, PNG or WebP, and at most `AI_UPLOAD_MAX_BYTES` (10 MB). The size is checked from
    `file_size` before the download and again on the bytes. Other images are rejected with a
    message (US3-5). The bytes become a `ContentFile` passed to `handle_message(image=…)`. The 003
    `ChatMessage.image` storage and 30-day purge then apply (FR-013).
  - Audio: stored on `WhatsAppInboundMessage.media` (FileField). The 30-day purge is extended to
    these files.
  - On a download failure or expiry, ask the shopper to send it again (edge case).
- **Outbound product photos**: upload the product image once to `POST /{phone-number-id}/media`
  and cache the returned media id in `WhatsAppMediaUpload(product_image, media_id, uploaded_at)`,
  reused for 25 days (Meta keeps them 30). Send `image: {id, caption: "<name> — <price> TZS"}`.
  Up to 3 per reply (FR-015). Products are picked from `payload.products` in this order: the ones
  whose name appears in the reply text first, then the remaining payload order.
- **Rationale**: uploading works in development (localhost media isn't reachable by Meta) and in
  production, with one code path.
- **Alternatives**: sending `image.link` with public media URLs (needs public S3 in every
  environment, and two code paths).

## R8. Payment message (FR-016)

- **Decision**: whenever a turn or Confirm tap produces `payload.payment` / `payload.order`, the
  server sends its own text, independent of the model. It contains the order number and server
  total. For **card**, it adds `payment.checkout_link`. For **mobile money** (the default), Stakaba
  pushes a PIN prompt and there is no URL, so the message says "check your phone for the PIN
  prompt", and offers a card link on request.
- **Rationale**: Constitution II (totals from the DB, SC-005). The 003 checkout already chooses the
  method.
- **Alternatives**: forcing card links on WhatsApp (worse for TZ shoppers; mobile money is the
  default rail).

## R9. Speech-to-text (FR-011)

- **Decision**: a new client `ai.clients.transcribe(audio_bytes, filename) -> {text, language,
  duration}`. It calls an **OpenAI-compatible** `POST {AI_SPEECH_BASE_URL}/audio/transcriptions`
  (`model=AI_SPEECH_MODEL`, `response_format=verbose_json`) through the existing `openai` SDK.
  Errors raise `ModelUnavailable`. Fakes plug in through `use_fakes(speech=…)`.
  - Development and production run the same small sidecar `ai/whisper` (FastAPI + faster-whisper,
    on CPU with `int8` in dev and on GPU with `float16` in prod). It exposes that one endpoint. The
    swap is configuration only (Constitution III; faster-whisper is named in its technology list).
  - Checks: audio file size at most `WHATSAPP_VOICE_MAX_BYTES` (2 MB; at WhatsApp's Opus bitrate,
    2 minutes is ~250 KB) before the call. `duration > WHATSAPP_VOICE_MAX_SECONDS` (120) or empty
    text after the call → "please type or send a shorter note". A detected language of `sw` or `en`
    is passed to `handle_message(language=…)`.
  - The reply starts with `🎤 Nimesikia: "…"` / `🎤 I heard: "…"`, cut to 200 characters.
- **Rationale**: one HTTP contract for dev and prod, the same pattern as SigLIP (`ai/siglip`).
  vLLM and speaches also serve this route, so the sidecar is replaceable.
- **Alternatives**: running faster-whisper inside Celery (adds torch/ctranslate2 to the app image),
  or using the `speaches` image directly (fine for production, but unpinned model management; kept
  as a production option because the contract is the same).

## R10. 24-hour window, templates, outbound sending (FR-017, FR-018, FR-022)

- **Decision**:
  - `WhatsAppContact.last_inbound_at` holds the WhatsApp `timestamp` of the shopper's latest
    message.
  - `outbound.send_text/send_image/send_buttons` raise `WindowClosed` when
    `now - last_inbound_at >= 24h`. Only `send_template` skips the check.
  - Every send first writes a `WhatsAppOutboundMessage(status=queued)`.
  - Delivery runs in order inside `deliver(ids)`. On a transient error (HTTP 5xx, timeouts, Graph
    codes 1/2/4/80007/130429/131016/131048/131056), the task re-queues itself with the remaining
    ids. It uses up to 4 attempts with a countdown of 10 s, 60 s, 5 min. On a permanent error
    (131026 undeliverable, 131047 window closed, 131051 unsupported, 132xxx template, 190 token, and
    other 4xx), the message is marked `failed` with the code and reason and not retried. A
    per-recipient permanent error (131026/131047) also fails the rest of that batch.
  - Order updates always use templates (FR-022). Template names come from settings, one per event
    and the follow-up. The language code is `sw` or `en` from `contact.language`.
- **Rationale**: Meta returns 131047 for free-form messages outside the window. Checking first
  avoids the cost and gives staff a clear reason (FR-024).
- **Alternatives**: free-form text for updates inside the window (FR-022 says templates).

## R11. Rate limits (FR-019) and link-code attempts (FR-008)

- **Decision**: the limits are counted from the database. The processing task counts the contact's
  inbound rows with `received_at` in the last 60 s and the last 24 h.
  - Over `WHATSAPP_RATE_PER_MINUTE` (10) or `WHATSAPP_RATE_PER_DAY` (200): the row is set to
    `rate_limited`, the message is recorded (`record_only`), and one "please slow down" note is
    sent. The note is sent only if `contact.slowdown_notice_at` is older than that window.
  - Link codes: at most 5 wrong codes per contact per hour (`WhatsAppLinkAttempt` rows, or a count
    on the contact with a window start).
- **Rationale**: exact and testable. There is no cache dependency, and the dev cache is locmem per
  process.
- **Alternatives**: the DRF throttle (HTTP-request scoped, not usable in a task), or Redis
  counters.

## R12. Conversation reset after 7 days (FR-007a)

- **Decision**: in the processing task, before the turn, check whether
  `contact.conversation` is missing, deleted by the 90-day purge, or
  `now - contact.last_inbound_at >= WHATSAPP_RESET_DAYS` (7) with the state `active`. In those
  cases:
  - Create a new `Conversation(channel=whatsapp, user=contact.user, language=contact.language)`.
    A guest's old cart is moved over (`cart=old.cart`). A customer uses their user cart.
  - Remove cart lines whose product is inactive or has `stock < quantity`, and capture their names.
  - `checkout_details`, `pending_checkout_at` and `last_order` start empty.
  - Send a short note listing the removed items, if any.
  - A `needs_human` conversation is never reset.
- **Rationale**: matches the clarification, with no stale context fed to the model.

## R13. Account linking (FR-008)

- **Decision**:
  - `POST /api/whatsapp/link/code/` (authenticated customer) creates a 6-character code from an
    unambiguous alphabet (no 0/O/1/I), shown as `LINK-7KQ4XM`. Only its sha256 is stored, with a
    10-minute expiry, and older unused codes of that user are invalidated. The response holds the
    code, `expires_at`, and
    `wa_link = https://wa.me/<WHATSAPP_BUSINESS_NUMBER digits>?text=<url-encoded "LINK-7KQ4XM">`.
  - Inbound text containing `\bLINK-[A-Z2-9]{6}\b` (case-insensitive) is handled before the
    assistant. If the code is valid and unused:
    1. Mark it used.
    2. If the number is linked to a different user, refuse.
    3. If the user was linked to another number, unlink that number (one number per account).
    4. Set `contact.user`, and `user.whatsapp_verified=True`.
    5. Merge the conversation's guest cart into the user cart (`orders.services.merge_carts`).
    6. Set `conversation.user`.
    7. Confirm in the shopper's language.
  - A wrong code records an attempt and sends "the code didn't work". After 5 wrong codes in an
    hour, the shopper gets the same answer without checking the code.
  - `GET /api/whatsapp/link/` returns `{linked, number (masked), linked_at}`.
    `DELETE /api/whatsapp/link/` unlinks and keeps the conversation history. The next WhatsApp turn
    is a guest again, with a new empty guest cart and `phone_orders` still visible.
- **Rationale**: the clarification and FR-008. Hashed codes mean a DB read doesn't leak live codes.
  The pre-filled wa.me text makes it one tap.

## R14. Order updates (FR-021)

- **Decision**: a `post_save` receiver on `orders.OrderEvent` (created, not raw) for the statuses
  `paid`, `out_for_delivery`, `delivered`, `cancelled` and `expired` queues
  `notify_order_status(order_id, status)` on commit.
  - The task returns early if there is no `WhatsAppOrder` (web orders, US5-4) or if
    `contact.updates_allowed` is false.
  - `WhatsAppOrderNotification.objects.get_or_create(order, status)`. If the row isn't created,
    stop (a replay).
  - Send the template with the order number and `money(order.total)` from the DB.
  - A send failure is recorded on the outbound row and the notification (`failed`) for staff. It
    never touches the order.
- **STOP / acha**: inbound text that is exactly `stop`, `acha`, `unsubscribe` or `sitaki`
  (trimmed, case-insensitive) sets `updates_allowed=False` and gets a confirmation. `start` or
  `anza` turns updates back on. Neither reaches the assistant.
- **Rationale**: `orders.transition()` is the one place each status change goes through, and it
  always writes an `OrderEvent`. Payment replays don't create a second event, and the unique row
  guards anyway.

## R15. Message splitting (FR-014)

- **Decision**: `split_text(text, limit=WHATSAPP_TEXT_LIMIT=4096)`. It tries to split at a blank
  line, then a newline, then a sentence end (`. `, `? `, `! `), then whitespace. It never splits
  inside a token (URLs and numbers have no spaces), and it never splits at a space between a number
  and `TZS`/`Tsh` or between `TZS` and a number. Each chunk has its whitespace trimmed, and the
  chunks are sent in order in one `deliver` batch.

## R16. Testing approach (Constitution VI, FR-025)

- `apps/whatsapp/graph.py` has a `GraphClient` with `send`, `upload_media`, `get_media` and
  `download`, plus `use_fake(FakeGraph)`, following the `ai.clients.use_fakes` pattern.
  `FakeGraph` records the payloads it receives, returns `wamid.FAKE…` ids, and can be scripted to
  raise transient or permanent errors.
- `ai.testing.FakeSpeech` returns a scripted `{text, language, duration}` or raises
  `ModelUnavailable`.
- Webhook tests sign the payloads with a test `WHATSAPP_APP_SECRET` through a helper
  `signed_post(client, payload)`. Payload builders live in `apps/whatsapp/testing.py`
  (`text_message`, `image_message`, `audio_message`, `button_reply`, `status_update`).
- Celery runs eagerly in tests (existing `backend/conftest.py`). The advisory lock is exercised
  with a real Postgres (the test DB on port 5434).
- Opt-in tests:
  - `@pytest.mark.sandbox` tests send a real text and template to `WHATSAPP_SANDBOX_TO` through
    Meta's test number. They are skipped when the env vars are unset.
  - `@pytest.mark.live_models` covers a real whisper transcription of a fixture clip.
- The voice eval for SC-007 is a `whatsapp_voice_eval` management command over a labelled clip set
  (`apps/whatsapp/eval/voice/`, ≥ 20 clips). Clips are recorded later, and the command and format
  ship now.
