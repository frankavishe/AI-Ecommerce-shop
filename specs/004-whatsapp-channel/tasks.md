# Tasks: WhatsApp Shopping Channel

**Input**: Design documents from `specs/004-whatsapp-channel/`

**Prerequisites**: plan.md, spec.md, research.md (R1–R16), data-model.md, contracts/ (webhook.md,
outbound.md, link-api.md, admin-api.md, speech-endpoint.md), quickstart.md

**Tests**: required (Constitution VI).
- In each story, the tests are written first and must fail before implementation.
- The Graph API, whisper and the chat model are always faked: `FakeGraph`, `FakeSpeech`, and the
  003 fakes from `backend/conftest.py`.
- Paths are relative to the repo root.
- Run the tests from `backend/` with
  `DATABASE_URL=postgres://shop:shop@localhost:5434/shop .venv/Scripts/python -m pytest`.

## Phase 1: Setup

- [X] T001 Create the app skeleton `backend/apps/whatsapp/`: `__init__.py`, `apps.py`
  (`WhatsappConfig`; `ready()` imports `notifications`), empty `models.py`, `urls.py`,
  `tests/__init__.py`, `management/__init__.py`, `management/commands/__init__.py`, and
  `eval/voice/.gitkeep`. Add `"apps.whatsapp"` to `INSTALLED_APPS` in
  `backend/config/settings.py`, and `path("api/whatsapp/", include("apps.whatsapp.urls"))` in
  `backend/config/urls.py`.
- [X] T002 [P] Add these settings to `backend/config/settings.py`, read from env with the given
  defaults:
  - Credentials: `WHATSAPP_PHONE_NUMBER_ID=""`, `WHATSAPP_BUSINESS_NUMBER=""`,
    `WHATSAPP_ACCESS_TOKEN=""`, `WHATSAPP_APP_SECRET=""`, `WHATSAPP_VERIFY_TOKEN=""`.
  - Graph: `WHATSAPP_GRAPH_URL="https://graph.facebook.com"`, `WHATSAPP_GRAPH_VERSION="v23.0"`.
  - Templates: `WHATSAPP_TEMPLATE_ORDER_PAID="order_paid"`,
    `WHATSAPP_TEMPLATE_ORDER_OUT_FOR_DELIVERY="order_out_for_delivery"`,
    `WHATSAPP_TEMPLATE_ORDER_DELIVERED="order_delivered"`,
    `WHATSAPP_TEMPLATE_ORDER_CANCELLED="order_cancelled"`,
    `WHATSAPP_TEMPLATE_ORDER_EXPIRED="order_expired"`,
    `WHATSAPP_TEMPLATE_FOLLOW_UP="follow_up"`.
  - Limits: `WHATSAPP_RATE_PER_MINUTE=10`, `WHATSAPP_RATE_PER_DAY=200`,
    `WHATSAPP_RESET_DAYS=7`, `WHATSAPP_VOICE_MAX_SECONDS=120`,
    `WHATSAPP_VOICE_MAX_BYTES=2*1024*1024`, `WHATSAPP_TEXT_LIMIT=4096`,
    `WHATSAPP_MAX_PRODUCT_PHOTOS=3`.
  - Other: `WHATSAPP_FAKE_GRAPH=False`, `WHATSAPP_LOCK_NAMESPACE=4004`.
  - Speech: `AI_SPEECH_BASE_URL="http://localhost:8091/v1"`, `AI_SPEECH_MODEL="small"`,
    `AI_SPEECH_TIMEOUT=120`.
  - Throttle rate `"whatsapp_link_code": "5/hour"`.
- [X] T003 [P] Add the `WHATSAPP_*` and `AI_SPEECH_*` variables with comments (dev values from
  `specs/004-whatsapp-channel/quickstart.md` §2) to `.env.example`.
- [X] T004 [P] In `backend/pytest.ini`, change the `sandbox` marker description to
  `sandbox: live calls to the Stakaba sandbox / Meta WhatsApp test number (run with: pytest -m sandbox)`.
- [X] T005 [P] Move the `shoe_catalog`, `conversation` and `png_bytes` fixtures from
  `backend/apps/ai/tests/conftest.py` to `backend/conftest.py`, so `apps/whatsapp/tests` can use
  them. Keep `embedder` in the ai conftest. `pytest apps/ai` must still pass.

## Phase 2: Foundational (blocks all stories)

### Models

- [X] T006 Write the models in `backend/apps/whatsapp/models.py` exactly per `data-model.md`:
  - `WhatsAppContact`: `wa_id` char(20) unique; `phone` char(16) unique; `profile_name`
    char(120) blank; `user` OneToOne→User null SET_NULL; `linked_at` null; `conversation`
    FK→ai.Conversation null SET_NULL `related_name="+"`; `language` sw/en default sw;
    `updates_allowed` default True; `last_inbound_at` null; `slowdown_notice_at` null;
    timestamps. Add a property `window_open` (`now - last_inbound_at < 24h`).
  - `WhatsAppInboundMessage`: `wa_message_id` char(128) **unique**; `contact` CASCADE; `type`
    enum text/image/audio/button/unsupported; `raw_type` char(32); `sent_at`; `received_at`
    auto; `text`; `button_id` char(256) blank; `media_id` char(128) blank; `media_mime`
    char(64) blank; `media` FileField `whatsapp/audio/%Y/%m/` null; `transcript` blank;
    `transcript_language` char(8) blank; `duration_s` float null; `status` enum
    received/processing/answered/recorded/rejected/failed/rate_limited default received; `error`
    char(64) blank; `chat_message` FK→ai.ChatMessage null SET_NULL; `processed_at` null. Indexes
    `(contact, status, sent_at, id)` and `(contact, received_at)`.
  - `WhatsAppOutboundMessage`: `contact` CASCADE; `conversation` null SET_NULL; `kind` enum
    text/image/buttons/template; `trigger` enum assistant/staff/system/order_update/payment;
    `body` JSON; `text`; `batch` UUID; `position` smallint; `wa_message_id` char(128) unique null;
    `status` enum queued/sent/delivered/read/failed/skipped default queued; `status_at` null;
    `attempts` default 0; `error_code` char(16) blank; `error` blank; `staff_user` null SET_NULL;
    `created_at`. Index `(batch, position)`.
  - `WhatsAppOrder`: `order` OneToOne PK CASCADE `related_name="whatsapp"`; `contact` CASCADE
    `related_name="orders"`; `created_at`.
  - `WhatsAppOrderNotification`: `order` CASCADE; `status` char(20); `outbound` null SET_NULL;
    `state` enum sending/sent/failed/skipped; `created_at`. **Unique `(order, status)`**.
  - `WhatsAppCheckoutPrompt`: UUID pk; `conversation` CASCADE; `contact` CASCADE; `fingerprint`
    char(64); `method` char(16); `network` char(16) blank; `total` Decimal(12,2); `order` null
    SET_NULL; `created_at`.
  - `WhatsAppLinkCode`: `user` CASCADE; `code_hash` char(64) unique; `expires_at`; `used_at`
    null; `used_by` FK contact null SET_NULL; `created_at`.
  - `WhatsAppLinkAttempt`: `contact` CASCADE; `created_at`.
  - `WhatsAppMediaUpload`: `product_image` OneToOne PK CASCADE; `media_id` char(128);
    `uploaded_at`.
- [X] T007 Run `makemigrations whatsapp` to create
  `backend/apps/whatsapp/migrations/0001_initial.py`. Add `STAFF = "staff", "Staff"` to
  `ChatMessage.Role` in `backend/apps/ai/models.py`, and run `makemigrations ai` (a choices-only
  migration).

### Building blocks (tests first)

- [X] T008 [P] Write `backend/apps/whatsapp/tests/test_building_blocks.py`, with these cases:
  - `verify_signature`: a correct `sha256=` header passes; a wrong digest, a missing header, a
    non-`sha256=` prefix and an empty configured secret all fail.
  - `verify_token`: constant-time match; an empty configured token always fails.
  - `split_text`: text under the limit stays one chunk. At the limit it splits at a blank line,
    then a newline, then a sentence end, then whitespace. It never splits inside a URL or a
    number, or between `50,000` and `TZS`.
  - `classify_error`: the transient and permanent codes from `contracts/outbound.md`.
  - `advisory_lock`: a second acquire on another connection returns False while the first holds
    it (`@pytest.mark.django_db(transaction=True)` and a raw second psycopg connection).
- [X] T009 [P] Implement `backend/apps/whatsapp/signature.py` (`verify_signature(raw: bytes,
  header: str) -> bool` using `hmac.compare_digest`, and `verify_token(given) -> bool`) per
  research R1.
- [X] T010 [P] Implement `backend/apps/whatsapp/graph.py`:
  - `GraphError(code, title, http_status, transient: bool)`
  - `classify_error(...)` per the `contracts/outbound.md` error-class table
  - `GraphClient` with `send(body) -> wa_message_id`, `get_media(media_id) -> {url, mime_type,
    file_size}`, `download(url) -> bytes`, and `upload_media(bytes, mime) -> media_id`. It uses
    `httpx` with a bearer token and a 20 s timeout.
  - `NotConfigured` when the token or number id is empty.
  - `get_client()` and `use_fake(fake)` / `reset_fake()`.
  - A `LoggingGraph` that is used when `WHATSAPP_FAKE_GRAPH` is set and `DEBUG` is on.
- [X] T011 [P] Implement `backend/apps/whatsapp/locks.py`: an `advisory_lock(contact_id)` context
  manager that yields `True`/`False`, using `pg_try_advisory_lock(WHATSAPP_LOCK_NAMESPACE, id)`
  and `pg_advisory_unlock` in `finally` (research R3).
- [X] T012 [P] Implement `backend/apps/whatsapp/texts.py` with every sw/en fixed text from
  `contracts/outbound.md` ("Server-built texts"), plus `text(key, lang, **kw)` and
  `format_tzs(Decimal)` (thousands separator, using `ai.tools.money` rounding).
- [X] T013 Implement `backend/apps/whatsapp/testing.py`:
  - `FakeGraph`: records `sent` bodies and returns `wamid.FAKE<n>`. `fail_next(code, transient)`
    scripts errors. `media` maps id → (bytes, mime, size). `uploads` returns `media.FAKE<n>`.
  - Payload builders `text_message`, `image_message`, `audio_message`, `button_reply`,
    `unsupported_message` and `status_update`, all wrapped in the webhook envelope of
    `contracts/webhook.md`.
  - `signed_post(client, payload, secret=None)`.
- [X] T014 Add the fixtures to `backend/apps/whatsapp/tests/conftest.py`:
  - an autouse fixture that sets the `WHATSAPP_*` test settings (secret `test-secret`, verify
    `test-verify`, number id `test-number`, token `test-token`, business number `+255700000000`)
    and installs a fresh `FakeGraph`, exposed as fixture `graph`
  - `contact_factory(wa_id="255742000331", **kw)`
  - `deliver_inbound(payload)` (a signed POST plus the eager drain)
- [X] T015 Write (before T016/T017; must fail first) `backend/apps/whatsapp/tests/test_outbound.py`:
  - window closed → `WindowClosed` and no row
  - a template sends with the window closed
  - the batch order is kept
  - a transient error: `deliver_batch` returns `"retry"`, the remaining rows stay queued, and
    the patched `deliver.retry` is called with countdowns 10/60/300; after the 4th attempt the
    remaining rows are `failed`
  - a linked `WhatsAppOrderNotification` follows its outbound row to `sent` or `failed`
  - 131026 → failed + skipped
  - not configured → failed with code
  - a cached media upload is reused, and re-uploaded after 25 days

- [X] T016 Implement `backend/apps/whatsapp/outbound.py` (research R10, R15) so the outbound
  parts of T008 pass:
  - `split_text`
  - `WindowClosed`
  - `queue_text(contact, text, trigger, conversation=None, staff_user=None, batch=None)`,
    `queue_image(contact, media_id, caption, …)`, `queue_buttons(contact, body, buttons, …)` and
    `queue_template(contact, name, params, …)`. The first three raise `WindowClosed` unless
    `contact.window_open`, and every function creates `WhatsAppOutboundMessage(status=queued)`
    rows in order within a batch.
  - `flush(batch)`: queues `tasks.deliver(batch_id)` on commit.
  - `product_media_id(product_image)`: uploads once and caches it in `WhatsAppMediaUpload` for
    25 days.
- [X] T017 Implement a pure `deliver_batch(batch_id) -> "done" | "retry"` in
  `backend/apps/whatsapp/outbound.py`, and a thin Celery task `deliver(batch_id)` in
  `backend/apps/whatsapp/tasks.py` (`bind=True`, `max_retries=4`) that calls it and, on
  `"retry"`, raises `self.retry(countdown=[10, 60, 300][retries])`:
  - It sends the queued rows in `position` order, and sets `wa_message_id`, `status=sent`,
    `status_at` and `attempts`.
  - Transient `GraphError`: re-raise `self.retry(countdown=[10, 60, 300][retries])` for the
    remaining rows. After the last retry, the rest are marked `failed`.
  - Permanent recipient errors 131026/131047: the row is `failed` and the rest `skipped`.
  - Other permanent errors: that row is `failed` and the batch continues.
  - `NotConfigured`: `failed`, `error_code="not_configured"`, logged at ERROR.
  - Whenever a row becomes `sent`, `failed` or `skipped`, update any
    `WhatsAppOrderNotification` with `outbound=row` to the same state (H1).
  - In eager mode the task does not retry. Tests drive `deliver_batch` directly and patch
    `deliver.retry` (H2).
### 003 hooks (research R4)

- [X] T018 Write `backend/apps/ai/tests/test_channel_hooks.py`:
  - `handle_message(record_only=True)` stores the user message with `meta` in `payload` and calls
    no model.
  - `verified_phone` pre-fills the checkout phone in `collect_guest_details`/`checkout`.
  - `order_status` with `phone_orders` and no number returns the latest phone order. With the
    number of an order outside `phone_orders`, it still requires the phone.
  - `checkout(confirm=false)` sets `AgentReply.summary` (total, fee, method, network,
    fingerprint inputs).
  - `AgentReply.incoming` is the stored user message.
  - The `/api/ai/chat` response keys are unchanged.
- [X] T019 Implement T018 in `backend/apps/ai/agent.py` and `backend/apps/ai/tools.py`:
  - Add the keyword-only `verified_phone=None, phone_orders=None, meta=None, record_only=False` to
    `handle_message`.
  - Add `ToolContext.verified_phone`, `phone_orders` and `checkout_summary`.
  - Change `prefilled()` to use `verified_phone` as the phone default.
  - Scope `order_status` as in research R4 item 3.
  - Have `checkout` set `ctx.checkout_summary` on both summary paths.
  - Add `AgentReply.summary` and `AgentReply.incoming`, defaulted so existing callers work.
  - `pytest apps/ai` must stay green.

**Checkpoint**: `pytest apps/whatsapp/tests/test_building_blocks.py
apps/whatsapp/tests/test_outbound.py apps/ai` passes, and `makemigrations --check` is clean.

## Phase 3: User Story 1 – Shopper chats with the shop on WhatsApp (P1) 🎯 MVP

**Goal**: a signed text message from any number gets the 003 assistant's reply on WhatsApp, once,
in order, with product photos, rate limits and a fallback.

**Independent test**: a signed text from a new number creates a contact and a WhatsApp
conversation, runs the scripted model once, and sends one reply with DB product names and prices
to that number (`FakeGraph.sent`).

### Tests (write first, must fail)

- [X] T020 [P] [US1] Write `backend/apps/whatsapp/tests/test_webhook.py`:
  - GET handshake: OK returns the challenge as text/plain; a wrong token, wrong mode or empty
    configured token returns 403.
  - A POST with a bad or missing signature returns 403 with zero rows and no task (SC-001).
  - A valid text POST returns 200 and creates a contact (E.164 `phone`, `profile_name`) and an
    inbound row.
  - The same payload posted 5 times gives one inbound row and one assistant run (SC-002).
  - Another `phone_number_id` is ignored.
  - Non-WABA JSON returns 200 and is ignored.
  - Status callbacks move an outbound row forward only (`read` then `delivered` stays `read`),
    and `failed` stores the error code and title.
  - An unknown status id is ignored.
- [X] T021 [P] [US1] Write `backend/apps/whatsapp/tests/test_processing.py`:
  - A new number gets a Swahili reply listing only active DB products with DB prices (US1-1).
  - A follow-up uses the history (US1-2).
  - Up to 3 product photos are sent, with the caption "<name> — <price> TZS" from the DB
    (US1-3, SC-005).
  - Three messages queued out of order are processed by `sent_at` (FR-005).
  - The 11th message in a minute is `rate_limited` and saved, with exactly one slow-down note
    for the window (FR-019; also the per-day variant through settings).
  - Model down: the fallback text is sent, the inbound row is `failed/model_unavailable`, and
    the message is saved (US1-7, SC-008).
  - A message older than 24 h on arrival is `recorded` and not answered.
  - A turn that exceeds `AI_CHAT_TIMEOUT` sends exactly one fallback and no late reply.
  - A long reply is split in order.
  - The contact language follows the conversation.
  - `last_inbound_at` never moves backwards.
- [X] T022 [P] [US1] Write `backend/apps/whatsapp/tests/test_reset.py` (FR-007a):
  - After 7 days of silence, a new conversation is created. The guest cart carries over minus
    inactive and out-of-stock lines, and the note lists the removed names. `checkout_details` and
    `last_order` are reset. `WhatsAppOrder` rows are untouched.
  - Under 7 days, the same conversation is kept.
  - A `needs_human` conversation is never reset.
  - A conversation deleted by the 90-day purge is replaced.

### Implementation

- [X] T023 [US1] Implement `backend/apps/whatsapp/parsing.py`: `parse(payload) -> list[Change]`
  with the contact, message and status dataclasses, using the type mapping table in
  `contracts/webhook.md`. `sent_at` comes from the unix `timestamp`. It tolerates missing keys.
- [X] T024 [US1] Implement `WebhookView` in `backend/apps/whatsapp/views.py`:
  - Settings: `authentication_classes=[]`, `permission_classes=[AllowAny]`,
    `throttle_classes=[]`, csrf-exempt.
  - GET handshake.
  - POST: verify the signature on `request.body` first. Then, in one atomic block, upsert the
    contacts and `get_or_create` the inbound rows; only new rows trigger
    `on_commit(drain_contact.delay)`. Apply status callbacks forward only.
  - Document it with `extend_schema(tags=["whatsapp-webhook"])`.
  - Route `webhook/` in `backend/apps/whatsapp/urls.py`.
- [X] T025 [US1] Implement `drain_contact(contact_id)` in `backend/apps/whatsapp/tasks.py`
  (`soft_time_limit = AI_CHAT_TIMEOUT + 60`):
  - Take the `advisory_lock`. If it is held, return.
  - Reset `processing` rows older than `AI_CHAT_TIMEOUT + 120 s` to `received`.
  - Loop over the oldest `received` row by `(sent_at, id)` → `processing.process(inbound)`.
  - Release the lock, re-check for `received` rows, and loop if any (research R3).
- [X] T026 [US1] Implement `backend/apps/whatsapp/processing.py`, following steps 1–8 of
  `contracts/webhook.md` "Processing pipeline", for the `text` and `unsupported` types:
  - `current_conversation(contact)`, including the reset and cart pruning of research R12.
  - `rate_limited(contact, inbound)` (research R11).
  - The needs-human `record_only` path, which sends nothing.
  - `run_turn(contact, conversation, inbound, text, image=None, language=None, prefix="")`. It
    calls `agent.handle_message(...)` with `verified_phone=contact.phone`,
    `phone_orders=Order.objects.filter(whatsapp__contact=contact)`,
    `user=contact.user`, and `meta={"whatsapp": {"type", "wa_message_id"}}`.
  - `send_reply(contact, conversation, reply, prefix)`: the text chunks, then the product photos,
    picked as in research R7 (names found in the text first, max
    `WHATSAPP_MAX_PRODUCT_PHOTOS`, product's first image via `product_media_id`), as one batch.
  - Setting `inbound.chat_message`, `status`, `processed_at` and `contact.language`.
- [X] T027 [US1] Handle `WindowClosed` inside `send_reply`: mark the inbound `answered` with error
  `window_closed` and log it. This only happens for delayed messages, so it never raises.
- [X] T028 [US1] Register read-only Django admins for the contact, inbound and outbound models in
  `backend/apps/whatsapp/admin.py`, with list filters by status and type.

**Checkpoint**: T020–T022 pass. US1 works end to end with fakes.

## Phase 4: User Story 2 – Shopper orders and pays from WhatsApp (P2)

**Goal**: cart, details, Confirm button or typed yes, a payment message with the DB total,
phone-verified order lookup, and account linking (including the web card).

**Independent test**: through simulated messages only, add a product, give the details, tap
Confirm, and check that the payment text belongs to an order whose lines and total match the DB.
Then "oda yangu iko wapi?" returns that order without asking for the phone.

### Tests (write first, must fail)

- [X] T029 [P] [US2] Write `backend/apps/whatsapp/tests/test_checkout.py`:
  - The WhatsApp number is offered as the contact phone, so only name, region and street are
    needed (US2-1).
  - A typed confirm sends the server payment text: card → `checkout_link`; mobile money → the
    PIN-prompt text. The total equals `Order.total` (US2-2, SC-005). A `WhatsAppOrder` row is
    created.
  - The summary is followed by a buttons message whose body total comes from the DB and whose ids
    are `confirm:<uuid>`/`change:<uuid>`.
  - A Confirm tap places exactly one order with no model call (`chat_model` receives nothing).
  - A second tap on the same Confirm creates no second order and resends the payment text.
  - A Confirm after a cart change, an older prompt, or more than 10 minutes is refused, and a
    fresh summary with new buttons is sent.
  - A foreign or unknown prompt id gets `button_expired`.
  - Change → `handle_message` with "Nataka kubadilisha kitu".
  - US2-4/5/6: the number's own orders need no number or phone; another number's order needs
    both; a registered-but-unlinked phone shows only WhatsApp orders.
  - Two numbers get separate conversations and carts, and neither can reach the other's cart or
    orders (FR-010).
  - SC-004 scripted flow: from question to payment in ≤ 6 inbound messages.
- [X] T030 [P] [US2] Write `backend/apps/whatsapp/tests/test_linking.py`:
  - API: GET when not linked or linked (masked number); POST creates `LINK-XXXXXX` (alphabet
    `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`, only the hash stored, older codes voided, `wa_link`
    pre-filled); throttled at 5 per hour; 503 when not configured; DELETE unlinks and clears
    `whatsapp_verified`; anonymous → 401.
  - In chat: a valid code links the number, merges the guest cart into the user cart, the
    conversation acts as the user (account orders and saved address), and the reply is `link_ok`
    (US2-7).
  - Wrong, expired or used code → `link_failed`, nothing linked (US2-8).
  - The 6th wrong code within an hour is not checked.
  - A number linked to another user → `link_taken`.
  - A user's previous number is unlinked on a new link.
  - The code inside a longer sentence still matches.
  - After an unlink (API), the next WhatsApp turn runs as a guest in a new conversation, and
    the earlier WhatsApp orders are still visible through `phone_orders`.

### Implementation

- [X] T031 [US2] Implement `backend/apps/whatsapp/checkout_buttons.py` (research R6):
  - `fingerprint(conversation, ctx_user)`: sha256 over sorted `(product_id, qty, unit_price)`,
    the normalized `prefilled` details, method, network, fee and total.
  - `send_prompt(contact, conversation, summary, batch)`: creates `WhatsAppCheckoutPrompt` and
    queues the buttons (`confirm_body` text, titles ≤ 20 characters).
  - `handle_confirm(contact, prompt_id)`: locks the prompt row and follows the rules of research
    R6 step by step, calling `ai.tools.run_tool(ctx, "checkout", {...})`. It stores user and
    assistant `ChatMessage`s for the tap.
  - `handle_change(...)`.
- [X] T032 [US2] In `backend/apps/whatsapp/processing.py`:
  - Route the `button` type to `checkout_buttons`.
  - After each turn, create a `WhatsAppOrder` if `conversation.last_order_id` changed.
  - When `reply.payload["payment"]` or `["order"]` is set, add the server payment text
    (`payment_card` / `payment_mobile`) to the batch.
  - Call `send_prompt` when `reply.summary` is set, as the last item of the batch.
- [X] T033 [US2] Implement `backend/apps/whatsapp/linking.py` (research R13):
  - `issue_code(user)`
  - `redeem(contact, conversation, code)`, which uses `orders.services.merge_carts` and sets
    `conversation.user` and `cart=None`
  - `unlink(user)`: clears `contact.user`, `linked_at` and `whatsapp_verified`, and points
    `contact.conversation` at a new guest conversation with a new guest cart
  - `CODE_RE = re.compile(r"\bLINK-([A-Z2-9]{6})\b", re.I)`
  - the attempt limit through `WhatsAppLinkAttempt`

  Hook it into the control-word step of `processing.py`.
- [X] T034 [US2] Implement `LinkView` (GET, DELETE) and `LinkCodeView` (POST, `ScopedRateThrottle`
  scope `whatsapp_link_code`) in `backend/apps/whatsapp/views.py`, with serializers in
  `backend/apps/whatsapp/serializers.py`. Route `link/` and `link/code/`. Responses follow
  `contracts/link-api.md`, and the views carry `extend_schema(tags=["whatsapp"])`.
- [X] T035 [US2] Regenerate the schema with
  `.venv/Scripts/python manage.py spectacular --file ../web/openapi.yml --validate`, then run
  `npm run gen:api` in `web/`.
- [X] T036 [P] [US2] Add the `account.whatsapp.*` strings to `web/src/i18n/sw.ts` and
  `web/src/i18n/en.ts`: title, explanation, getCode, codeLabel, expiresIn, openWhatsApp,
  copyCode, copied, linkedAs, linkedOn, unlink, confirmUnlink, cancel, unlinked, notConfigured.
- [X] T037 [US2] Implement `web/src/lib/queries/whatsapp.ts`: `useWhatsAppLink({poll})` (polls
  every 5 s while a code is shown, for up to 10 min), `useCreateLinkCode()` and `useUnlink()`,
  through `bff` from `@/lib/api/client`, the same way as the existing queries.
- [X] T038 [US2] Implement `web/src/app/(shop)/account/whatsapp-link-card.tsx` per
  `contracts/link-api.md` "Web" (not linked / code shown with countdown / linked + inline unlink
  confirm, no browser dialogs). Render it under `<ProfileForm />` in
  `web/src/app/(shop)/account/page.tsx`.
- [X] T039 [P] [US2] Write `web/e2e/account-whatsapp.spec.ts` (Playwright, using the e2e backend):
  log in, get a code, check that the code and `wa.me` link are shown, simulate a link (backend
  helper or API), check the card flips to linked, then unlink. Add a vitest unit test for the
  countdown formatting in `web/src/app/(shop)/account/whatsapp-link-card.test.tsx`.

**Checkpoint**: T029–T030 and T039 pass. A full scripted WhatsApp purchase works with buttons.

## Phase 5: User Story 3 – Shopper sends a photo or a voice note (P3)

**Goal**: photos go to the 003 photo search; voice notes are transcribed by self-hosted whisper and
answered with a "heard" line.

**Independent test**: a simulated photo of a catalog product puts that product in the reply. A
simulated Swahili voice note (`FakeSpeech` transcript) gets a reply that answers it and starts with
`🎤 Nimesikia`.

### Tests (write first, must fail)

- [ ] T040 [P] [US3] Write `backend/apps/whatsapp/tests/test_media.py`:
  - A photo with or without a caption runs `handle_message` with the image, and the matching
    product is shown (US3-1).
  - A photo > 10 MB (by `file_size` and by bytes) or a GIF → `image_rejected`, no model call
    (US3-5, FR-012).
  - A media download failure → `media_retry`.
  - A voice note → `FakeSpeech` → the reply starts with the heard line, the transcript and
    language are stored on the inbound row and in `ChatMessage.payload.whatsapp.transcript`
    (US3-2, FR-013).
  - Voice > 120 s, > 2 MB or with an empty transcript → `voice_retry` (US3-3).
  - Speech down → the fallback and `failed/speech_unavailable`.
  - Each unsupported type (video, document, sticker, location, contacts) → `unsupported`, no
    model call (US3-4).
  - The purge deletes audio files older than 30 days.
- [ ] T041 [P] [US3] Write `backend/apps/ai/tests/test_speech_client.py`: `transcribe()` maps
  `language` `swahili`/`sw` → `sw` and `english`/`en` → `en`, with others → None. Connection or
  HTTP errors → `ModelUnavailable`. `use_fakes(speech=…)` overrides the client.

### Implementation

- [ ] T042 [US3] Add `transcribe(audio_bytes, filename) -> {"text", "language", "duration"}` to
  `backend/apps/ai/clients.py`. It uses `openai.OpenAI(base_url=AI_SPEECH_BASE_URL,
  timeout=AI_SPEECH_TIMEOUT).audio.transcriptions.create(model=AI_SPEECH_MODEL,
  file=(filename, bytes), response_format="verbose_json")`, with the `speech` override. Add
  `FakeSpeech` (scripted results or raises) to `backend/apps/ai/testing.py`.
- [ ] T043 [US3] Add `download_media(inbound, max_bytes, allowed_mimes)` to
  `backend/apps/whatsapp/processing.py`, and image and audio handlers following step 6 of
  `contracts/webhook.md`:
  - Images go in as a `ContentFile(name=f"wa-{id}.{ext}")`.
  - Audio is saved to `inbound.media`.
  - The voice prefix uses `texts.heard`, cut to 200 characters.
  - The detected language is passed to `handle_message(language=…)`.
- [ ] T044 [US3] Extend `purge_old_conversations` in `backend/apps/ai/tasks.py` to delete
  `WhatsAppInboundMessage.media` files older than 30 days and clear the field. Import it lazily
  to avoid an app cycle.
- [ ] T045 [P] [US3] Create the sidecar `ai/whisper/`:
  - `app.py`: FastAPI. It loads `WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE,
    compute_type=WHISPER_COMPUTE_TYPE)` at startup and serves `POST /v1/audio/transcriptions`
    (multipart `file`, `model`, `response_format`). The response is
    `{"text", "language", "duration"}`. It also serves `GET /health`.
  - `requirements.txt` with pinned versions of `fastapi`, `uvicorn` and `faster-whisper`.
  - A `Dockerfile` modelled on `ai/siglip/Dockerfile`.

  The contract is `contracts/speech-endpoint.md`.
- [ ] T046 [P] [US3] Add a `whisper` service to `infra/docker-compose.yml`:
  - profile `ai`, port `8091:8091`
  - a volume for the model cache
  - `WHISPER_MODEL=small`, `WHISPER_DEVICE=cpu`, `WHISPER_COMPUTE_TYPE=int8`
  - `AI_SPEECH_BASE_URL: ${AI_SPEECH_BASE_URL_DOCKER:-http://whisper:8091/v1}` in the backend
    anchor

  Add a `whisper` service to `infra/docker-compose.gpu.yml` with `large-v3`, `cuda` and
  `float16`.

**Checkpoint**: T040–T041 pass. `docker compose --profile ai up whisper` answers `/health`.

## Phase 6: User Story 4 – Staff take over a WhatsApp conversation (P4)

**Goal**: admins list flagged WhatsApp conversations, read the history (transcripts, photos),
reply within the window or send the follow-up template, and release.

**Independent test**: flag a WhatsApp conversation, send a staff reply as an admin, and check that
it reaches the number (`FakeGraph`) and is stored as a `staff` message. The assistant stays silent
while the conversation is flagged.

### Tests (write first, must fail)

- [ ] T047 [P] [US4] Write `backend/apps/whatsapp/tests/test_admin.py`:
  - While flagged, shopper messages are saved and nothing is sent (US4-1).
  - Within the window, a staff reply → 202, a `ChatMessage(role=staff)`, an outbound
    `trigger=staff` with `staff_user` (US4-2).
  - With the window closed, free text → 409 `window_closed` with `templates`, and nothing is sent
    (US4-3, SC-006). `{"template": "follow_up"}` → 202 with a template body.
  - A non-WhatsApp conversation → 400. An empty text → 400.
  - A customer or rider → 403, anonymous → 401 (US4-4).
  - After release, the assistant answers again (US4-5).
  - The admin list with `?channel=whatsapp&state=needs_human` includes the `whatsapp` block, and
    the detail view includes `staff` messages and the voice transcript.
  - `GET /api/whatsapp/admin/outbound/?status=failed` lists the failures.

### Implementation

- [ ] T048 [US4] In `backend/apps/ai/views.py`, add a `channel` filter (with an
  `OpenApiParameter`) to `AdminConversationViewSet`. In `backend/apps/ai/serializers.py`, add a
  `whatsapp` SerializerMethodField to the admin serializers (number, profile_name, window_open,
  window_closes_at, or null), looking up `WhatsAppContact` by `conversation`. Prefetch it to
  avoid N+1 queries.
- [ ] T049 [US4] Implement `StaffReplyView` (`POST
  /api/whatsapp/admin/conversations/<uuid:pk>/reply/`, `IsShopAdmin`) per
  `contracts/admin-api.md`. It uses `outbound.queue_text` (split) or
  `queue_template(WHATSAPP_TEMPLATE_FOLLOW_UP)`, catches `WindowClosed` → 409, and stores a
  `ChatMessage(role=STAFF)`.
- [ ] T050 [US4] Implement `OutboundListView` (`GET /api/whatsapp/admin/outbound/`, filters
  `status`, `contact`, paginated, `IsShopAdmin`) with its serializer. Add `order_number` from the
  `WhatsAppOrderNotification` link. Route both admin views in `backend/apps/whatsapp/urls.py`.
- [ ] T051 [P] [US4] Register read-only admins for `WhatsAppOrderNotification` and
  `WhatsAppLinkCode` (exclude `code_hash` from the display) in `backend/apps/whatsapp/admin.py`.

**Checkpoint**: T047 passes.

## Phase 7: User Story 5 – Shopper gets order updates on WhatsApp (P5)

**Goal**: WhatsApp-placed orders get one template update per status change (paid, out for
delivery, delivered, cancelled, expired), which STOP/acha can turn off.

**Independent test**: place an order from a simulated number, mark it paid through the Stakaba
flow, then move it to out_for_delivery. Exactly one template is sent per change, and replays send
nothing.

### Tests (write first, must fail)

- [ ] T052 [P] [US5] Write `backend/apps/whatsapp/tests/test_notifications.py`:
  - A paid order through `payments.services.apply_provider_status` → one `order_paid` template
    with the DB number and total (US5-1, FR-022). Replaying the payment webhook 5 times → still
    one (US5-3, SC-002).
  - out_for_delivery with the window closed → template in the contact's language (US5-2).
  - delivered, cancelled and expired (via `orders.tasks.expire_unpaid_orders`) → their templates.
  - A web order → nothing (US5-4).
  - `updates_allowed=False` → notification `skipped`, nothing sent.
  - STOP, acha and sitaki → `stopped` reply, updates off, no model call. START/anza → back on.
  - A transient send failure returns `"retry"` from `deliver_batch` (with `deliver.retry`
    patched) and keeps the order state. A final failure → notification
    `failed` and visible in the outbound list (US5-5).

### Implementation

- [ ] T053 [US5] Implement `backend/apps/whatsapp/notifications.py`. A `post_save` receiver on
  `orders.OrderEvent` (created, not raw, status in the five) runs
  `transaction.on_commit(notify_order_status.delay(order_id, status))`. It is connected in
  `apps.py` with a `dispatch_uid`.
- [ ] T054 [US5] Implement `notify_order_status(order_id, status)` in
  `backend/apps/whatsapp/tasks.py` (research R14):
  - No `WhatsAppOrder` → return.
  - `get_or_create` the `WhatsAppOrderNotification` → if it already exists, return.
  - Updates off → `skipped`.
  - Otherwise `queue_template` with the template setting for the status and params
    `[order.number, format_tzs(order.total)]` (paid) or `[order.number]`, link the outbound row,
    and leave the notification `state=sending`. `deliver_batch` (T017) moves it to `sent` or
    `failed`.
- [ ] T055 [US5] Add the STOP and START control words (`stop|acha|sitaki|unsubscribe`,
  `start|anza`; trimmed, case-insensitive, whole message) to the control-word step of
  `backend/apps/whatsapp/processing.py`, with the `stopped` and `started` replies.

**Checkpoint**: T052 passes.

## Phase 8: Polish & Cross-Cutting

- [ ] T056 [P] Implement the management command
  `backend/apps/whatsapp/management/commands/whatsapp_simulate.py`. Options: `--from`, and one of
  `--text`, `--image PATH`, `--audio PATH` or `--button ID`. It builds a payload with
  `testing.py`, signs it with `WHATSAPP_APP_SECRET`, and POSTs it to the local webhook (or calls
  the view in-process with `--inline`). It is DEBUG-only. When `WHATSAPP_FAKE_GRAPH` is set, the
  media ids are served from the given file.
- [ ] T057 [P] Implement `backend/apps/whatsapp/management/commands/whatsapp_voice_eval.py`. It
  reads `eval/voice/cases.json` (`[{"file", "language", "expect_product"}]`), transcribes each
  clip, runs a turn on a throwaway conversation, and prints a hit rate per language.
  `--min 0.8` exits non-zero below the threshold (SC-007).
- [ ] T058 [P] Write `backend/apps/whatsapp/tests/test_sandbox.py` (`@pytest.mark.sandbox`,
  skipped unless `WHATSAPP_SANDBOX_TO` and the real credentials are set). It sends one text and
  one `follow_up` template through the real `GraphClient` and asserts a `wamid` comes back.
- [ ] T059 [P] Write `backend/apps/whatsapp/tests/test_live_speech.py`
  (`@pytest.mark.live_models`). It transcribes a short Swahili fixture clip
  `apps/whatsapp/eval/voice/sample_sw.ogg` through the real endpoint and asserts non-empty text.
- [ ] T060 Write the full validation run: `pytest -q` (003 stays green),
  `makemigrations --check --dry-run`, `spectacular --validate`, `npm run gen:api` with no diff,
  `npx vitest run`, and `npx playwright test e2e/account-whatsapp.spec.ts`. Fix any failures.
- [ ] T061 Add `--timing` to `whatsapp_simulate` (prints webhook→reply-queued seconds per
  message) and run quickstart §2 (simulated end-to-end) against the local CPU stack, and record the
  observed result (reply times, button flow, voice) in `specs/004-whatsapp-channel/quickstart.md`
  under a "Validation results" heading. SC-003 is checked the same way on the GPU box when it
  exists. Until then, note it as pending.

## Dependencies

- **Setup (T001–T005)** → **Foundational (T006–T019)** → the user stories.
- **US1 (T020–T028)** must be done before US2–US5. They all use the webhook, the pipeline and the
  outbound layer.
- **US2, US3, US4 and US5** are independent of each other after US1. They do touch shared files:
  - `processing.py` is shared by US2, US3 and US5. Do those edits one after another.
  - `tasks.py` is shared by US5 (and was already touched in US1).
- The web tasks T036–T039 depend on T034 and T035 (the API and generated types).
- Polish comes after the stories you want to ship.

## Parallel examples

- Phase 1: T002 ∥ T003 ∥ T004 ∥ T005 after T001.
- Phase 2: T008 ∥ T009 ∥ T010 ∥ T011 ∥ T012 after T006/T007. T018/T019 (the ai hooks) can run in
  parallel with T013–T017.
- US1: the tests T020 ∥ T021 ∥ T022.
- US2: T029 ∥ T030. Then the backend (T031–T034) ∥ T036 (i18n).
- US3: T040 ∥ T041, and the sidecar T045 ∥ T046 at any time.
- Across stories, once US1 is done, US3's sidecar, US4 and US5 can be built by different people.

## Implementation Strategy

1. **MVP = Phases 1–3 (US1)**: WhatsApp text chat with the assistant, safe (signature,
   idempotency, ordering, limits) and tested with fakes.
2. **Add US2**: sales through WhatsApp with the Confirm buttons and account linking.
3. **Add US3**: photos and voice (needs the whisper sidecar running for manual checks).
4. **Add US4 and US5**: staff takeover and order updates (needs Meta-approved templates for real
   sends).
5. **Polish**: the simulator, the voice evaluation, sandbox runs, the full validation.
