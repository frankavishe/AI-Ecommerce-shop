---
description: "Task list for Commerce Checkout"
---

# Tasks: Commerce Checkout (Cart, Orders, ClickPesa Payments)

**Input**: Design documents from `/specs/001-commerce-checkout/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md

**Tests**: Required. Constitution VI makes test-first non-negotiable; within each story the tests
come before the implementation.

**Organization**: Tasks are grouped by user story. All paths are relative to the repo root.

## Phase 1: Setup

- [X] T001 Create app packages `backend/apps/orders/` and `backend/apps/payments/` (`__init__.py`, `apps.py`, `migrations/__init__.py`, `tests/__init__.py`) following `backend/apps/catalog/`
- [X] T002 Update `backend/config/settings.py`: add `apps.orders` and `apps.payments` to INSTALLED_APPS; `CACHES = {"default": env.cache("CACHE_URL", default="locmemcache://")}`; `CLICKPESA_BASE_URL` (default `https://api.clickpesa.com/third-parties`), `CLICKPESA_CLIENT_ID`, `CLICKPESA_API_KEY`, `CLICKPESA_CHECKSUM_KEY`; `SHOP_DEFAULT_DELIVERY_FEE` (Decimal, default 5000); `ORDER_REMINDER_MINUTES=30`; `ORDER_EXPIRY_MINUTES=120`; `CELERY_BEAT_SCHEDULE` running reminders and expiry every 5 minutes
- [X] T003 [P] Add `CACHE_URL`, `CLICKPESA_BASE_URL`, `SHOP_DEFAULT_DELIVERY_FEE`, `ORDER_*` to `.env.example`, and `CACHE_URL: redis://redis:6379/1` to `infra/docker-compose.yml`
- [X] T004 [P] Create `backend/conftest.py` with shared fixtures: `api_client`, `customer`, `admin_user`, `auth_client(user)`, `product(stock=10, price=45000)`, `region` (Dar es Salaam, 3000)

## Phase 2: Foundational (blocks all stories)

- [X] T005 Create models in `backend/apps/orders/models.py`: `DeliveryRegion(name char(80) unique, fee decimal ≥0, is_active)`, `Cart(user FK null unique, token char(64) unique)`, `CartItem(cart, product, quantity ≥1; unique (cart, product))`, `Order(number char(12) unique, user null, contact_name, contact_phone E.164, region, district, street, notes, subtotal, delivery_fee, total, status choices, stock_released, placed_at, paid_at, reminder_sent_at, expires_at; indexes (status, placed_at), contact_phone)`, `OrderItem` (snapshot), `OrderEvent(status, actor null, source customer|admin|system|provider, note, created_at)`
- [X] T006 Create `Payment` in `backend/apps/payments/models.py`: `order FK`, `reference char(20) unique`, `amount`, `currency='TZS'`, `status pending|success|failed|mismatch`, `checkout_link URL(500)`, `provider_ref`, `channel`, `collected_amount null`, `raw_payload JSON`, timestamps
- [X] T007 Generate migrations `backend/apps/orders/migrations/0001_initial.py` and `backend/apps/payments/migrations/0001_initial.py`
- [X] T008 Implement core services in `backend/apps/orders/services.py`: `normalize_phone` (`0XXXXXXXXX`→`+255…`, validated with `apps.accounts.models.phone_validator`), `delivery_fee_for(region)`, `generate_order_number()` (8 chars from `ABCDEFGHJKMNPQRSTUVWXYZ23456789`), the `TRANSITIONS` map from data-model.md, `transition(order, status, source, actor=None, note="")` (raises `InvalidTransition`, writes `OrderEvent`, releases stock on cancelled/expired), `release_stock(order)` guarded by `stock_released`
- [X] T009 [P] Implement `backend/apps/payments/clickpesa.py`: `checksum(payload, key)` (drop checksum/checksumMethod, recursive key sort, compact JSON, HMAC-SHA256 hex), `verify_checksum`, `ClickPesaClient` (token cached 55 min under `clickpesa:token`; `create_checkout_link(reference, amount, name, phone, description)`; `query_payments(reference)`; raises `PaymentProviderUnavailable` when unconfigured or on HTTP/network errors; injectable `httpx` transport)
- [X] T010 [P] Write `backend/apps/payments/tests/test_clickpesa.py`: checksum matches a known vector, token minted once and reused, link request body (`totalPrice` as string, `orderCurrency` TZS, phone without `+`), unconfigured → `PaymentProviderUnavailable`
- [X] T011 Register admin classes in `backend/apps/orders/admin.py` and `backend/apps/payments/admin.py` (Order with OrderItem/OrderEvent/Payment inlines, read-only money fields)

**Checkpoint**: models are migrated and the ClickPesa client is tested.

## Phase 3: User Story 1 – Guest buys and pays (P1) 🎯 MVP

**Goal**: guest cart → checkout → payment link → verified webhook → paid.
**Independent Test**: `pytest apps/orders/tests/test_cart.py apps/orders/tests/test_checkout.py apps/orders/tests/test_concurrency.py apps/payments/tests/test_webhook.py apps/payments/tests/test_confirm.py`

### Tests (write first, they must fail)

- [X] T012 [P] [US1] `backend/apps/orders/tests/test_cart.py`: a guest GET creates a cart and token; add/update/remove/clear; inactive product rejected; quantity above stock rejected with the available count; quantity 0 removes the line; a client `price` field is ignored; subtotal is computed
- [X] T013 [P] [US1] `backend/apps/orders/tests/test_checkout.py`: guest checkout creates an `awaiting_payment` order with item snapshot, the region fee (and default fee for an unknown region), stock deducted, cart emptied, `payment_url` from the mocked client; client `total` ignored; empty cart → 400 `empty_cart`; invalid phone → 400; local phone normalised; provider down → 201 with `payment_url: null` and `payment_error`
- [X] T014 [P] [US1] `backend/apps/orders/tests/test_concurrency.py` (`transaction=True`): 20 threads check out the last unit → exactly 1 order, stock 0
- [X] T015 [P] [US1] `backend/apps/payments/tests/test_webhook.py`: valid checksum → 200 and order paid (query mocked SUCCESS); bad checksum → 400 and no change; unknown reference → 200 ignored; the same webhook 5× → one success payment and one `paid` event; no checksum key configured → accepted but still confirmed through the query
- [X] T016 [P] [US1] `backend/apps/payments/tests/test_confirm.py`: collected amount below total → payment `mismatch`, order `needs_review`; FAILED → payment failed, order stays awaiting; PROCESSING → no change

### Implementation

- [X] T017 [US1] Cart services in `backend/apps/orders/services.py`: `get_or_create_cart(request)` (user cart, or `X-Cart-Token` header, or a new guest cart), `add_item`, `set_quantity`, `remove_item`, `clear`, `cart_totals`
- [X] T018 [US1] `place_order(cart, contact, address, user=None)` in `backend/apps/orders/services.py`: `transaction.atomic`, conditional `filter(pk, stock__gte=qty, is_active=True).update(stock=F-qty)` ordered by product id, raises `OutOfStock`/`InactiveProduct`, snapshots items, computes totals, sets `expires_at`, writes the first event, empties the cart
- [X] T019 [US1] Payment services in `backend/apps/payments/services.py`: `start_payment(order)` (next reference `<number>P<n>`, creates `Payment`, calls the client, stores the link; on `PaymentProviderUnavailable` returns None plus an error) and `apply_provider_status(payment, records)` (success/settled with TZS amount ≥ total → payment success + order `paid`/`paid_at` if awaiting payment, else `needs_review`; lower amount → mismatch + `needs_review`; FAILED → failed; success is final)
- [X] T020 [US1] Celery task `confirm_payment(payment_id)` in `backend/apps/payments/tasks.py` using `select_for_update` on the payment
- [X] T021 [US1] Serializers in `backend/apps/orders/serializers.py`: `CartSerializer`, `AddItemSerializer`, `CheckoutSerializer` (guest fields or `address_id`; read-only money), `OrderSerializer` (items, events, `payment_url`), `DeliveryRegionSerializer`
- [X] T022 [US1] Views and urls in `backend/apps/orders/views.py`, `backend/apps/orders/urls.py`: `/cart/`, `/cart/items/`, `/cart/items/<product_id>/`, `/checkout/`, `/delivery-regions/` as in contracts/api.md, errors as `{"detail", "code"}`
- [X] T023 [US1] Webhook view and url in `backend/apps/payments/views.py`, `backend/apps/payments/urls.py`: verify checksum when a key is set (top level or `data`), look up `Payment` by `data.orderReference`, merge the payload into `raw_payload`, `confirm_payment.delay`, return 200 `{"received": true}`
- [X] T024 [US1] Include the urls in `backend/config/urls.py` (`api/` → orders, `api/payments/` → payments)

**Checkpoint**: the MVP money path works on its own.

## Phase 4: User Story 2 – Registered cart and order history (P2)

**Independent Test**: `pytest apps/orders/tests/test_customer_orders.py`

- [ ] T025 [P] [US2] `backend/apps/orders/tests/test_customer_orders.py`: user cart persists across clients; merge sums quantities capped at stock and deletes the guest cart; checkout with `address_id` copies the address (a later edit doesn't change the order); another user's `address_id` → 400; list shows only own orders newest first; another user's order → 404; guest lookup with matching phone → 200, wrong phone → 404; `pay/` issues a new link with reference `P2`, refused when not awaiting payment
- [ ] T026 [US2] Add `merge_carts(user_cart, guest_cart)` to `backend/apps/orders/services.py` and address checkout handling to `CheckoutSerializer`
- [ ] T027 [US2] Add `/cart/merge/`, `/orders/`, `/orders/<number>/`, `/orders/lookup/`, `/orders/<number>/pay/` to `backend/apps/orders/views.py` and `urls.py`

## Phase 5: User Story 3 – Admin manages orders (P3)

**Independent Test**: `pytest apps/orders/tests/test_admin_orders.py`

- [ ] T028 [P] [US3] `backend/apps/orders/tests/test_admin_orders.py`: filter by status, paid, date range; search by number/phone/name; detail includes payments; paid → processing writes an event with the actor; cancelling an awaiting order returns stock once; cancelled → paid → 400 `invalid_transition`; a customer or guest gets 401/403 on every admin endpoint; region CRUD admin-only
- [ ] T029 [US3] `OrderFilter` in `backend/apps/orders/filters.py` (`status`, `placed_after`, `placed_before`, `paid`)
- [ ] T030 [US3] Admin viewsets (`IsShopAdmin`) in `backend/apps/orders/views.py`: `/admin/orders/` list and detail (with payments), `/admin/orders/<number>/status/`, `/admin/delivery-regions/` CRUD; register them in `urls.py`

## Phase 6: User Story 4 – Reminders and expiry (P4)

**Independent Test**: `pytest apps/orders/tests/test_jobs.py`

- [ ] T031 [P] [US4] `backend/apps/orders/tests/test_jobs.py`: an order unpaid after 30 minutes gets `reminder_sent_at` and one event, and a second run sends no second reminder; an order past `expires_at` becomes `expired` and its stock is returned; a successful payment confirmed after expiry → `needs_review`
- [ ] T032 [US4] Tasks `send_payment_reminders` and `expire_unpaid_orders` in `backend/apps/orders/tasks.py` (each order handled in its own transaction with `select_for_update(skip_locked=True)`)

## Phase 7: Polish

- [ ] T033 Run `pytest`, `python manage.py makemigrations --check --dry-run`, `python manage.py spectacular --file schema.yml --validate`; fix any issues
- [ ] T034 [P] Mark specs/001-commerce-checkout/tasks.md done and update the project memory

## Dependencies

- Setup → Foundational → US1 → (US2, US3, US4 in any order; all build on US1's services)
- Within a story the tests come first; services come before views.

## Parallel examples

- Foundational: T009 + T010 alongside T005–T008.
- US1: T012–T016 (separate test files) in parallel.

## Implementation Strategy

MVP = Phases 1–3 (guest checkout + payment). Then US2 → US3 → US4, with a commit after each story.
