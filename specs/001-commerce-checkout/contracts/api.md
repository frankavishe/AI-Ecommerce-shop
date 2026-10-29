# API Contract: Commerce Checkout

Base path `/api/`. JSON in and out. Auth is an optional `Authorization: Bearer <JWT>`; guests send
`X-Cart-Token: <token>`. The machine-readable contract is the generated OpenAPI schema
(`/api/schema/`). This file pins the shapes the clients rely on.

## Shared shapes

```jsonc
// Cart
{ "token": "str", "items": [ { "product": {"id": 1, "name": "str", "slug": "str", "price": "45000.00", "stock": 9, "is_active": true},
  "quantity": 2, "unit_price": "45000.00", "line_total": "90000.00" } ],
  "item_count": 2, "subtotal": "90000.00" }

// Order (detail)
{ "number": "K7Q2M9XD", "status": "awaiting_payment", "contact_name": "str", "contact_phone": "+255712345678",
  "region": "str", "district": "str", "street": "str", "notes": "str",
  "subtotal": "90000.00", "delivery_fee": "3000.00", "total": "93000.00", "currency": "TZS",
  "placed_at": "iso", "paid_at": null, "expires_at": "iso",
  "items": [ {"product": 1, "product_name": "str", "unit_price": "45000.00", "quantity": 2, "line_total": "90000.00"} ],
  "events": [ {"status": "awaiting_payment", "source": "customer", "note": "", "created_at": "iso"} ],
  "payment_url": "https://..." }   // latest pending checkout link or null
```

Errors: `400 {"detail": "...", "code": "out_of_stock|inactive_product|empty_cart|invalid_transition|..."}`
or DRF field errors.

## Cart

| Method | Path | Body | Result |
|---|---|---|---|
| GET | `/cart/` | — | 200 Cart (created if missing; guests get a new token) |
| DELETE | `/cart/` | — | 204, cart emptied |
| POST | `/cart/items/` | `{product_id, quantity=1}` | 200 Cart; adds to the existing quantity |
| PATCH | `/cart/items/{product_id}/` | `{quantity}` | 200 Cart; 0 removes the line |
| DELETE | `/cart/items/{product_id}/` | — | 200 Cart |
| POST | `/cart/merge/` (auth) | `{cart_token}` | 200 Cart; guest cart merged and deleted |

## Checkout and orders

| Method | Path | Auth | Body | Result |
|---|---|---|---|---|
| GET | `/delivery-regions/` | any | — | 200 `[{name, fee}]` (active) + `default_fee` |
| POST | `/checkout/` | any | guest: `{contact_name, contact_phone, region, street, district?, notes?}`; user: same, or `{address_id, contact_name?, contact_phone?}` | 201 Order (with `payment_url`, possibly null + `payment_error`) |
| GET | `/orders/` | customer | — | 200 paginated own orders (summary) |
| GET | `/orders/{number}/` | owner | — | 200 Order |
| POST | `/orders/lookup/` | any | `{number, phone}` | 200 Order / 404 |
| POST | `/orders/{number}/pay/` | owner, or guest with `{phone}` | `{phone?}` | 200 `{payment_url}`; 400 if not awaiting payment |

## Admin (role admin)

| Method | Path | Notes |
|---|---|---|
| GET | `/admin/orders/` | filters `status`, `placed_after`, `placed_before`, `paid=true/false`; `search` = number/phone/name; newest first |
| GET | `/admin/orders/{number}/` | Order + `payments: [...]` |
| POST | `/admin/orders/{number}/status/` | `{status, note?}`, validated against the state machine |
| CRUD | `/admin/delivery-regions/` | `{name, fee, is_active}` |

## Payments webhook

| Method | Path | Notes |
|---|---|---|
| POST | `/payments/clickpesa/webhook/` | ClickPesa event body. 400 on invalid checksum (when a key is configured); otherwise 200 `{"received": true}` and confirmation is queued |
