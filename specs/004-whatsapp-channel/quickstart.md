# Quickstart: validating 004-whatsapp-channel

## 1. Automated tests (no Meta, no models)

From `backend/`, with the test DB on 5434 (see the local test setup notes):

```bash
DATABASE_URL=postgres://shop:shop@localhost:5434/shop .venv/Scripts/python -m pytest apps/whatsapp -q
DATABASE_URL=postgres://shop:shop@localhost:5434/shop .venv/Scripts/python -m pytest -q   # full suite (003 must stay green)
.venv/Scripts/python manage.py makemigrations --check --dry-run
.venv/Scripts/python manage.py spectacular --file ../web/openapi.yml --validate
```

Expected: everything passes. The Graph API is replaced by `FakeGraph` and whisper by `FakeSpeech`,
and the chat model uses the 003 fakes. The tests cover these spec scenarios:

| Area | Spec | Test module |
|---|---|---|
| Handshake, signature, ignored numbers | FR-001/002, SC-001, US1-4 | `test_webhook.py` |
| Duplicates and replays | FR-004, SC-002, US1-5 | `test_webhook.py`, `test_processing.py` |
| Order per number, lock, rate limit | FR-005, FR-019, US1-6 | `test_processing.py` |
| Text turn, photos ≤ 3, splitting, model down | US1-1/2/3/7, FR-014/015/020, SC-005/008 | `test_processing.py`, `test_outbound.py` |
| Checkout, buttons, phone-verified orders | US2, FR-009/016/016a, SC-004 | `test_checkout.py` |
| Link codes and the API | US2-7/8, FR-008 | `test_linking.py` |
| 7-day reset and cart pruning | FR-007a | `test_reset.py` |
| Photos and voice | US3, FR-011/012/013 | `test_media.py` |
| Staff reply, window, release, permissions | US4, FR-017/023/024, SC-006 | `test_admin.py` |
| Order updates, STOP, retries | US5, FR-021/022, FR-018 | `test_notifications.py`, `test_outbound.py` |

Web:

```bash
cd web && npm run gen:api && npx vitest run && npx playwright test e2e/account-whatsapp.spec.ts
```

## 2. Simulated end-to-end with no Meta account (local)

1. Put these in `.env`: `WHATSAPP_APP_SECRET=dev-secret`, `WHATSAPP_VERIFY_TOKEN=dev-verify`,
   `WHATSAPP_PHONE_NUMBER_ID=dev-number`, `WHATSAPP_BUSINESS_NUMBER=+255700000000`,
   `WHATSAPP_FAKE_GRAPH=true`. In DEBUG, the fake flag logs the outbound payloads instead of
   calling Meta.
2. Start the API and a worker, plus Ollama and SigLIP from 003. For voice, add
   `docker compose -f infra/docker-compose.yml --profile ai up -d whisper`.
3. Send a signed message:
   `python manage.py whatsapp_simulate --from 255742000331 --text "nataka viatu vyekundu"`.
   You can also use `--image path.jpg`, `--audio note.ogg` or `--button confirm:<id>`.
4. Expected: the worker log shows the outbound text, then up to 3 product photos (uploads are faked
   too). `GET /api/ai/admin/conversations/?channel=whatsapp` lists the conversation.
5. Continue: "weka ya kwanza kwenye kikapu", then "nataka kulipa", then name, region and street.
   Expected: a summary text and a Confirm/Change button message. Simulate the Confirm button with
   the id from the log. Expected: one order, and a payment text whose total equals
   `Order.total`. Simulating Confirm again sends no second order.

## 3. Real Meta test number (opt-in)

1. In Meta for Developers, create an app and add WhatsApp. Take the test number id, a permanent
   system-user token and the app secret.
2. Expose the API over HTTPS with `cloudflared tunnel --url http://localhost:8000`. Set the
   webhook URL to `https://<tunnel>/api/whatsapp/webhook/` with the verify token, and subscribe to
   `messages`. Expected: Meta reports the webhook as verified.
3. Set `WHATSAPP_FAKE_GRAPH=false` and the real `WHATSAPP_*` values. Add your phone as a test
   recipient.
4. Message the test number from your phone (text, a product photo, a Swahili voice note). Expected:
   replies within the CPU time budget, a "🎤 Nimesikia" line for voice notes, and photos with
   prices.
5. Sandbox tests: `WHATSAPP_SANDBOX_TO=2557XXXXXXXX pytest -m sandbox apps/whatsapp`. They send one
   text and one template. Templates must be approved first (see
   [contracts/outbound.md](contracts/outbound.md)).

## 4. Link an account (web)

1. Log in on the storefront, open `/account` and use "Link WhatsApp" → "Get link code".
2. Tap "Open WhatsApp", or send the `LINK-XXXXXX` text from the phone.
3. Expected: a "now linked" reply, and within about 5 s the card shows the masked number. Asking
   "oda zangu" in WhatsApp now lists the account's orders.

## 5. Voice evaluation (SC-007, production hardware)

`python manage.py whatsapp_voice_eval --dir apps/whatsapp/eval/voice` (≥ 20 labelled sw/en clips).
Expected: the target product is in the reply for ≥ 80% of clips. CPU numbers are informative only.
