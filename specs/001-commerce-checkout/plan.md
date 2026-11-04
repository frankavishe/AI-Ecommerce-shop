# Implementation Plan: Commerce Checkout (Cart, Orders, ClickPesa Payments)

**Branch**: `001-commerce-checkout` | **Date**: 2026-10-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-commerce-checkout/spec.md`

## Summary

Add two Django apps to the existing backend. `orders` holds the cart (guest token or user), delivery
regions, orders with an item snapshot, a status state machine and a timeline. `payments` holds the
ClickPesa client (token caching, hosted checkout link, status query, HMAC checksum), the `Payment`
records, the webhook, and Celery tasks for confirmation, reminders and expiry. Stock is deducted
with conditional atomic updates when the order is placed. Payment truth always comes from
ClickPesa's status query, not from webhook bodies.

## Technical Context

**Language/Version**: Python 3.13 (Docker image), Django 5.2

**Primary Dependencies**: DRF 3.16, simplejwt, django-filter, drf-spectacular, Celery 5.5, httpx
(all already in `backend/requirements.txt`; no new dependencies)

**Storage**: PostgreSQL 16 (`pgvector/pgvector:pg16`); Redis for the Celery broker and cache

**Testing**: pytest + pytest-django; ClickPesa mocked with `httpx.MockTransport`

**Target Platform**: Linux containers (`infra/docker-compose.yml`)

**Project Type**: web service (REST API for the Next.js web, the Flutter app and later the WhatsApp agent)

**Performance Goals**: checkout under 1 s excluding the ClickPesa call; webhook acknowledged in under 1 s

**Constraints**: no ClickPesa sandbox (R5); `orderReference` is alphanumeric, at most 20 chars and
unique per link (R2); 1 token mint per 3 minutes (R1)

**Scale/Scope**: a small shop: hundreds of orders per day, tens of concurrent shoppers

## Constitution Check

| Principle | How this plan complies | Status |
|---|---|---|
| I. Tanzania-first | Decimal TZS, aware datetimes, E.164 with `0…` → `+255…` normalisation | ✅ |
| II. Server is truth | Prices are read from `Product`, fees from `DeliveryRegion`; serializers ignore client prices; conditional stock updates (R7) | ✅ |
| III. Self-hosted AI / ClickPesa | ClickPesa only; no AI in this feature | ✅ |
| IV. Verified, idempotent integrations | HMAC checksum check, provider status re-query, success is final, unknown refs answered 200 | ✅ |
| V. Server-side roles | `IsShopAdmin` on admin views; owner/phone checks on orders; cart token for guests | ✅ |
| VI. Test-first | Tests written per story before implementation; HTTP mocked | ✅ |
| VII. API-first monolith | Two new apps in `backend/apps/`; endpoints in the spectacular schema | ✅ |

Post-design re-check: still passing; no violations to track.

## Project Structure

### Documentation (this feature)

```text
specs/001-commerce-checkout/
├── plan.md  research.md  data-model.md  quickstart.md
├── contracts/api.md
├── checklists/requirements.md
└── tasks.md
```

### Source Code

```text
backend/
├── config/settings.py        # INSTALLED_APPS, CACHES, CLICKPESA_*, ORDER_* settings, CELERY_BEAT_SCHEDULE
├── config/urls.py            # include orders + payments urls
├── conftest.py               # shared fixtures (api_client, users, products, regions)
└── apps/
    ├── orders/
    │   ├── models.py         # DeliveryRegion, Cart, CartItem, Order, OrderItem, OrderEvent
    │   ├── services.py       # cart ops, place_order, transition, release_stock, phone normalisation
    │   ├── serializers.py  views.py  urls.py  admin.py  filters.py  tasks.py
    │   └── tests/            # test_cart, test_checkout, test_concurrency, test_customer_orders,
    │                         # test_admin_orders, test_jobs
    └── payments/
        ├── clickpesa.py      # ClickPesaClient, checksum helpers, errors
        ├── models.py         # Payment
        ├── services.py       # start_payment(order), apply_provider_status(payment, records)
        ├── tasks.py          # confirm_payment
        ├── views.py  urls.py  admin.py
        └── tests/            # test_clickpesa, test_webhook, test_confirm
```

**Structure Decision**: the same app layout as `apps/accounts` and `apps/catalog`. Business rules
live in `services.py` so the WhatsApp agent tools (a later feature) can call them directly without
going through HTTP views.

## Complexity Tracking

No violations.
