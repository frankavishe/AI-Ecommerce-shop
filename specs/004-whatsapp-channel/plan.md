# Implementation Plan: WhatsApp Shopping Channel

**Branch**: `004-whatsapp-channel` | **Date**: 2026-11-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-whatsapp-channel/spec.md`

## Summary

A new Django app, `backend/apps/whatsapp`, connects the Meta WhatsApp Cloud API to the 003
assistant.

- **Inbound**: a signed webhook stores each message once (unique WhatsApp id) and queues a
  per-number Celery drain task. The task holds a Postgres advisory lock and processes that number's
  messages in send order. It applies rate limits, the 7-day reset, control words (STOP and link
  codes) and the handoff state. Then it calls the unchanged `ai.agent.handle_message`:
  - text as-is
  - photos as the image argument
  - voice notes after a self-hosted whisper transcription
- **Outbound**: replies are split into chunks and sent in order with retries, and every send is
  recorded with its delivery status. The server also sends:
  - product photos
  - the payment message (built from DB totals)
  - Confirm/Change reply buttons, which place the order without the model
- **The 24-hour rule**: free-form sends check the window. Order updates (an `OrderEvent` signal)
  and the staff follow-up use approved templates.
- **Staff**: staff reply through a new admin endpoint. The 003 admin list and release are reused.
- **Web**: customers link their number from a "Link WhatsApp" card on the account page.
- **Tests**: tests fake the Graph API and whisper. Real calls are opt-in (`sandbox`,
  `live_models`).

## Technical Context

**Language/Version**: Python 3.14 (`backend/.venv`), Django 5.2, DRF 3.16; TypeScript / Next.js
(web card)

**Primary Dependencies**:

- Existing: `httpx` (Graph API), `openai` 1.109 (speech client via `audio.transcriptions`),
  Celery + Redis, Pillow, drf-spectacular.
- New sidecar `ai/whisper`: FastAPI, uvicorn, `faster-whisper`.
- No new backend Python dependencies.

**Storage**: PostgreSQL 16 (new `whatsapp_*` tables, advisory locks), media storage for voice audio
(30-day purge)

**Testing**: pytest + pytest-django with `FakeGraph`, `FakeSpeech` and the 003 fake models.
Opt-in `sandbox` (Meta test number) and `live_models` (real whisper). Web: vitest + one Playwright
spec.

**Target Platform**: Linux containers (app box + GPU box). Windows dev with CPU models and a
`cloudflared` tunnel for the real webhook.

**Project Type**: web service (existing Django monolith) + one model sidecar + a small web UI
addition

**Performance Goals**:

- Webhook acknowledged in < 1 s with no outbound network calls in the request.
- Production: 90% of text replies ≤ 10 s, and 90% of voice notes under 30 s ≤ 15 s (SC-003).
- Fallback when the model is down ≤ 30 s (SC-008).

**Constraints**:

- Free-form messages only within 24 h of the shopper's last message.
- Text ≤ 4096 characters per message, at most 3 buttons, button title ≤ 20 characters.
- Images ≤ 10 MB (JPEG, PNG, WebP).
- Voice ≤ 2 min, ≤ 2 MB.
- 10 messages per minute and 200 per day per number (configurable).
- No price from the model or the client.

**Scale/Scope**: one business number. Low hundreds of WhatsApp conversations a day at launch. Per
number, at most one turn runs at a time.

## Constitution Check

*Checked against constitution v2.0.0 before research, and again after the design.*

| Principle | How this plan complies | Status |
|---|---|---|
| I. Tanzania-first | Numbers stored in E.164 (`normalize_phone`). Totals are Decimal from the DB, formatted by `ai.tools.money`. All fixed texts and templates exist in sw and en, with Swahili as the default. | ✅ |
| II. Server is source of truth | Payment and confirm texts and button bodies are built from `Order` and `cart_totals`. A Confirm tap re-checks a fingerprint of the server cart and details, then runs the 003 `checkout` tool server-side (R6). Product captions use the DB price. | ✅ |
| III. Self-hosted AI, Stakaba | Speech goes through an env-configured OpenAI-compatible endpoint served by our faster-whisper sidecar (R9). Transcripts and captions are passed to the model as shopper text, not instructions, and the 003 data-wrapping is unchanged. Payments use `payments.services.start_payment` through the 003 tool. | ✅ |
| IV. Verified, idempotent integrations | HMAC-SHA256 over the raw body plus a constant-time verify-token check (R1). Unique `wa_message_id`, forward-only statuses, unique `(order, status)` notifications (R2, R14). Fast 200 with work done in Celery. Secrets only in `.env`. | ✅ |
| V. Server-side roles | Each number maps to exactly one contact and conversation. A guest sees only `phone_orders`; a linked customer sees their orders. Admin endpoints use `IsShopAdmin`, and the link API requires login. 003 tool role checks are unchanged. | ✅ |
| VI. Test-first | Each story's tests come first. Graph and whisper are always faked. Failure paths are covered: bad signature, replay, window closed, transient and permanent send errors, model or speech down, stale Confirm, wrong link codes. | ✅ |
| VII. API-first monolith | One new app under `backend/apps/whatsapp`. All new endpoints are in drf-spectacular and the web types are regenerated. The whisper sidecar is justified below. | ✅ (see Complexity Tracking) |

Post-design re-check (after data-model and contracts): no new violations. The changes to 003 are
additive and keyword-only (research R4), and `POST /api/ai/chat` output is unchanged.

## Project Structure

### Documentation (this feature)

```text
specs/004-whatsapp-channel/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── webhook.md          # inbound handshake, signature, payload mapping, processing pipeline
│   ├── outbound.md         # Graph calls, error classes, fixed texts, templates
│   ├── link-api.md         # customer link API + web card
│   ├── admin-api.md        # staff reply, outbound list, extended 003 admin
│   └── speech-endpoint.md  # whisper transcription contract + sidecar
├── checklists/requirements.md
└── tasks.md                # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── apps/whatsapp/
│   ├── apps.py                 # ready(): connect the OrderEvent signal
│   ├── models.py               # Contact, InboundMessage, OutboundMessage, Order, OrderNotification,
│   │                           # CheckoutPrompt, LinkCode, LinkAttempt, MediaUpload
│   ├── migrations/0001_initial.py
│   ├── signature.py            # verify_signature(raw, header), verify_token()
│   ├── parsing.py              # webhook JSON → contact / message / status dataclasses
│   ├── graph.py                # GraphClient (send, get_media, download, upload_media), error
│   │                           # classification, use_fake(); a logging fake when WHATSAPP_FAKE_GRAPH
│   ├── outbound.py             # send_text/image/buttons/template, window check, split_text, deliver()
│   ├── texts.py                # fixed sw/en texts (contracts/outbound.md)
│   ├── processing.py           # the pipeline: rate limit, reset, control words, handoff, by-type
│   │                           # handlers, reply assembly, WhatsAppOrder linking
│   ├── checkout_buttons.py     # fingerprint(), send_prompt(), handle_confirm(), handle_change()
│   ├── linking.py              # issue_code(), redeem(), unlink()
│   ├── notifications.py        # OrderEvent receiver, notify_order_status()
│   ├── locks.py                # advisory_lock(contact_id) context manager
│   ├── tasks.py                # drain_contact, deliver, notify_order_status
│   ├── views.py · serializers.py · urls.py · admin.py
│   ├── testing.py              # FakeGraph, payload builders, signed_post()
│   ├── management/commands/    # whatsapp_simulate.py, whatsapp_voice_eval.py
│   ├── eval/voice/             # labelled clips (added later) + cases.json format
│   └── tests/                  # test_webhook, test_processing, test_outbound, test_checkout,
│                               # test_linking, test_reset, test_media, test_admin,
│                               # test_notifications, test_sandbox (marker), test_live_speech (marker)
├── apps/ai/
│   ├── agent.py                # handle_message(+verified_phone, phone_orders, meta, record_only);
│   │                           # AgentReply.summary / .incoming
│   ├── tools.py                # ToolContext fields; prefilled() phone default; order_status scope;
│   │                           # checkout sets ctx.checkout_summary
│   ├── models.py               # ChatMessage.Role.STAFF (+ migration)
│   ├── clients.py              # transcribe() + use_fakes(speech=…)
│   ├── testing.py              # FakeSpeech
│   ├── views.py / serializers.py  # admin list: ?channel=, whatsapp block
│   └── tasks.py                # purge: WhatsApp audio older than 30 days
├── config/settings.py          # WHATSAPP_*, AI_SPEECH_*, throttle scope, INSTALLED_APPS, urls
├── config/urls.py              # path("api/whatsapp/", include("apps.whatsapp.urls"))
└── pytest.ini                  # sandbox marker text now covers Stakaba + WhatsApp
ai/whisper/                     # Dockerfile, app.py, requirements.txt
infra/docker-compose.yml        # + whisper service (profile "ai"), AI_SPEECH_BASE_URL_DOCKER
infra/docker-compose.gpu.yml    # + whisper (cuda, large-v3)
.env.example                    # WHATSAPP_*, AI_SPEECH_*
web/src/app/(shop)/account/
├── page.tsx                    # renders <WhatsAppLinkCard/> under ProfileForm
└── whatsapp-link-card.tsx      # contracts/link-api.md
web/src/lib/queries/whatsapp.ts # useWhatsAppLink, useCreateLinkCode, useUnlink (TanStack Query via bff)
web/src/i18n/{sw,en}.ts         # account.whatsapp.*
web/e2e/account-whatsapp.spec.ts
```

**Structure Decision**: the feature extends the monolith with one app, `backend/apps/whatsapp`,
laid out like `payments` (a provider client, webhook views, tasks). The assistant stays in
`apps/ai`, which gets only additive hooks. The speech model is an external sidecar like
`ai/siglip`. The only web change is one card on the account page.

## Implementation notes

- **Reuse**:
  - `ai.agent.handle_message`, `ai.tools.run_tool` (Confirm path), `ai.tools.money` and
    `product_card`, `ai.clients.ModelUnavailable` and the `use_fakes` pattern,
    `ai.prompts.fallback`, `ai.images.prepare_image` (through 003 photo search).
  - `orders.services.normalize_phone`, `merge_carts`, `cart_totals`, `GUEST_CART_LIFETIME`.
  - `orders.views.payment_message` semantics and `payments.models.Payment.Method`.
  - `accounts.permissions.IsShopAdmin`.
  - `AdminConversationViewSet` (list, retrieve, release).
- **Webhook view**: a plain Django view (`csrf_exempt`), or an `APIView` with
  `authentication_classes = []`, `permission_classes = [AllowAny]` and `throttle_classes = []`.
  It reads `request.body` before any parser touches it, and is documented with `extend_schema`.
- **Advisory lock**: `SELECT pg_try_advisory_lock(%s, %s)` with
  `(WHATSAPP_LOCK_NAMESPACE, contact_id)`. Release it in `finally`. Use the default connection
  outside any atomic block. Tests run the eager task within the test transaction, and the lock
  remains valid at session level.
- **Transactions**: each inbound row is processed outside a long transaction. `handle_message`
  tools use their own atomics, as in 003. Status updates use small atomics. The outbound `deliver`
  is queued with `on_commit`.
- **Settings** (all from env):
  - `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_BUSINESS_NUMBER`, `WHATSAPP_ACCESS_TOKEN`,
    `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`
  - `WHATSAPP_GRAPH_URL`, `WHATSAPP_GRAPH_VERSION=v23.0`
  - `WHATSAPP_TEMPLATE_*`
  - `WHATSAPP_RATE_PER_MINUTE=10`, `WHATSAPP_RATE_PER_DAY=200`, `WHATSAPP_RESET_DAYS=7`
  - `WHATSAPP_VOICE_MAX_SECONDS=120`, `WHATSAPP_VOICE_MAX_BYTES=2097152`
  - `WHATSAPP_TEXT_LIMIT=4096`, `WHATSAPP_MAX_PRODUCT_PHOTOS=3`
  - `WHATSAPP_FAKE_GRAPH=false`
  - `AI_SPEECH_BASE_URL`, `AI_SPEECH_MODEL`, `AI_SPEECH_TIMEOUT`
  - Throttle scope `whatsapp_link_code: 5/hour`
- **Missing configuration** (edge case): with an empty token or number id, the webhook still
  stores messages, and `deliver` marks sends `failed` with `error_code="not_configured"` and logs
  an ERROR. The web shop is unaffected.
- **Order of a reply**:
  1. The "heard" line (voice), merged into the first text chunk.
  2. The text chunks.
  3. Up to 3 product photos.
  4. The payment message.
  5. The Confirm/Change buttons.

  Everything goes out as one `deliver` batch, so the order holds even across retries.
- **Delivery order across stories**: US1 (webhook, pipeline, outbound) and US2 (buttons, linking,
  phone orders, web card) come first. US3 (media and whisper sidecar), US4 (staff API) and US5
  (notifications and templates) can follow in parallel once US1's outbound layer exists.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Extra process `ai/whisper` (speech sidecar) | Voice notes need a self-hosted speech model behind an OpenAI-compatible endpoint (Constitution III). Ollama and TEI don't serve whisper, and vLLM's whisper support means a GPU box for dev too. | Running faster-whisper inside Celery would add ctranslate2 and the models to every app container and tie GPU hardware to the app box. The sidecar mirrors the accepted `ai/siglip` pattern and can be swapped for vLLM or speaches through config. |
| Small additive changes to the 003 assistant (`handle_message` keyword args, `ToolContext` fields) despite "reused unchanged" | FR-009 (number counts as a verified phone, offered as contact) and FR-016a (server-side summary for buttons) need channel facts inside the tool layer | Forking the agent loop for WhatsApp would make two loops that drift apart. Pre-filling checkout details from outside can't scope `order_status`. The web chat API is unchanged and the 003 tests stay green. |
