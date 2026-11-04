# Research: Commerce Checkout

Sources: https://docs.clickpesa.com/ (generate-token, generate-checkout-link, querying-for-payments,
webhooks, checksum pages), read 2026-10-28.

## R1. ClickPesa authentication

- **Decision**: `POST https://api.clickpesa.com/third-parties/generate-token` with headers
  `client-id` and `api-key`. The response `{"success": true, "token": "Bearer eyJ..."}` already
  includes the `Bearer ` prefix and is sent verbatim as `Authorization`. Cache the token in the Django
  cache for 55 minutes (it lives 1 hour).
- **Rationale**: ClickPesa allows only one successful token mint per client per IP every 3 minutes, so
  minting per request would hit 429s.
- **Alternatives**: minting per request (rejected because of rate limits).

## R2. Hosted checkout link

- **Decision**: `POST /third-parties/checkout-link/generate-checkout-url` with the "total amount"
  body variant: `totalPrice` (string), `orderReference`, `orderCurrency: "TZS"`, `customerName`,
  `customerPhone` (E.164 without `+`), `description`. Add `checksum` when a checksum key is
  configured. The response field `checkoutLink` is what the shopper opens.
- **Rationale**: the shop already computes the total on the server. Sending a single total avoids a
  second price calculation on the provider side.
- **Constraints**: `orderReference` must be **alphanumeric only** (no hyphens), at most 20 characters,
  and **unique per link**: reusing one returns 409.
- **Consequence**: each payment attempt gets its own reference `<ORDERNUMBER>P<n>` (e.g.
  `K7Q2M9XDP1`). This is stored on `Payment.reference`, which makes "request a new payment link"
  (FR-016) possible. Order numbers are 8 uppercase alphanumeric characters.
- The return URL after payment is set in the ClickPesa dashboard, not per request.

## R3. Payment confirmation

- **Decision**: `GET /third-parties/payments/{orderReference}` returns an **array** of payment
  records (`status` ∈ SUCCESS, SETTLED, PROCESSING, PENDING, FAILED; `collectedAmount`,
  `collectedCurrency`, `paymentReference`, `id`, `message`). An order is paid only if some record has
  status SUCCESS or SETTLED, currency TZS, and `collectedAmount >= order.total`.
- **Rationale**: constitution IV requires re-checking with the provider. The query result is the
  source of truth; the webhook only triggers the check.

## R4. Webhooks and checksum

- **Decision**: one endpoint `POST /api/payments/clickpesa/webhook/` handles the `PAYMENT RECEIVED`
  and `PAYMENT FAILED` events (`{"event": ..., "data": {..., "orderReference": ...}}`). When
  `CLICKPESA_CHECKSUM_KEY` is set, a `checksum` (top level or in `data`) is required and verified:
  remove `checksum`/`checksumMethod`, sort keys recursively, `json.dumps(separators=(",", ":"))`,
  HMAC-SHA256 with the key, lowercase hex, constant-time compare. An invalid checksum returns 400.
  Valid or unchecked events queue a Celery task that runs R3 and answers 200 right away. Unknown
  references are logged and answered with 200.
- **Rationale**: the docs don't say exactly where the checksum field sits in webhook bodies, so the
  check accepts both places. Even a forged-but-unchecked event can't mark an order paid, because R3
  asks ClickPesa directly.
- **Alternatives**: trusting the webhook body (rejected by constitution IV).

## R5. No sandbox

- **Finding**: "ClickPesa does not provide a sandbox". Every call moves real money. Before KYC the
  account is limited to TZS 100,000 in total and 100 API calls per day.
- **Decision**: all automated tests mock HTTP (`httpx.MockTransport`). Manual end-to-end checks use
  tiny real amounts (e.g. TZS 500 test products). When `CLICKPESA_CLIENT_ID` is empty, the client
  raises `PaymentProviderUnavailable` and checkout still creates the order with `payment_url: null`
  (it can be retried later).

## R6. Guest cart identity

- **Decision**: an opaque `cart token` (`secrets.token_urlsafe(32)`) returned in the cart body and
  sent back by clients in the `X-Cart-Token` header. Logged-in users get a cart tied to their user;
  `POST /api/cart/merge/` merges in a guest cart.
- **Rationale**: the API uses JWT, not cookies. Web, Flutter and the WhatsApp agent can all carry a
  header. Session cookies would break CORS and mobile use.

## R7. Stock safety

- **Decision**: at order placement, inside `transaction.atomic()`, run
  `Product.objects.filter(pk=..., stock__gte=qty).update(stock=F("stock") - qty)` for each line,
  ordered by product id. If any update affects 0 rows, raise `OutOfStock`, which rolls back the
  whole order. Releasing stock is the reverse update, guarded by `Order.stock_released`.
- **Rationale**: a conditional update is atomic in PostgreSQL and needs no explicit lock. Ordering
  by product id avoids deadlocks.

## R8. Scheduling

- **Decision**: Celery beat entries every 5 minutes for `send_payment_reminders` (orders unpaid
  after `ORDER_REMINDER_MINUTES=30`, `reminder_sent_at` null) and `expire_unpaid_orders` (unpaid past
  `expires_at` = placed + `ORDER_EXPIRY_MINUTES=120`).
- **Rationale**: Celery and beat are already in `infra/docker-compose.yml`. A 5-minute cadence meets
  SC-006 ("by the next scheduled run").

## R9. Caching

- **Decision**: `CACHES = {"default": env.cache("CACHE_URL", default="locmemcache://")}`. Docker
  compose sets `CACHE_URL=redis://redis:6379/1`.
- **Rationale**: the shared token cache across workers lives in Redis, while tests stay in-process.
