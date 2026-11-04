# Quickstart: Commerce Checkout validation

## Prerequisites

- Docker running. From the repo root: `docker compose -f infra/docker-compose.yml --env-file .env up -d db redis`
- Backend venv with `pip install -r backend/requirements.txt`

## Automated checks (from `backend/`)

```bash
python manage.py migrate
python manage.py makemigrations --check --dry-run   # expect: No changes detected
pytest                                              # all tests pass
python manage.py spectacular --file schema.yml --validate   # no errors; cart/checkout/orders/payments paths present
```

These tests prove the main behaviour:

| Scenario | Test module |
|---|---|
| Guest cart, checkout, payment link, webhook → paid, replay is idempotent | `apps/orders/tests/test_checkout.py`, `apps/payments/tests/test_webhook.py` |
| Client-sent prices ignored; out of stock; inactive product | `apps/orders/tests/test_cart.py`, `test_checkout.py` |
| Last-unit race (20 threads) → exactly one order | `apps/orders/tests/test_concurrency.py` |
| Registered cart, merge, saved address, history, guest lookup | `apps/orders/tests/test_customer_orders.py` |
| Admin list, filter, transitions, permissions | `apps/orders/tests/test_admin_orders.py` |
| Reminder and expiry jobs, late payment → needs_review | `apps/orders/tests/test_jobs.py`, `apps/payments/tests/test_confirm.py` |
| ClickPesa client (token caching, link, checksum) | `apps/payments/tests/test_clickpesa.py` |

## Manual end-to-end (real money, small amounts; ClickPesa has no sandbox)

1. Put `CLICKPESA_CLIENT_ID`, `CLICKPESA_API_KEY` (and `CLICKPESA_CHECKSUM_KEY` if checksum is
   enabled) in `.env`. In the ClickPesa dashboard, set the application's PAYMENT RECEIVED and PAYMENT
   FAILED webhooks to `https://<public-host>/api/payments/clickpesa/webhook/`. Use a tunnel such as
   cloudflared during development.
2. Create a TZS 500 product in `/django-admin/`.
3. `POST /api/cart/items/ {"product_id": <id>}`, keep the `token`, then
   `POST /api/checkout/` with the `X-Cart-Token` header and guest details.
4. Open `payment_url`, pay with mobile money. Within 1 minute,
   `POST /api/orders/lookup/ {"number", "phone"}` shows `status: "paid"`.
