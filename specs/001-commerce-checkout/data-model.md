# Data Model: Commerce Checkout

All money values are `Decimal(12,2)` in TZS. All timestamps are aware datetimes (Africa/Dar_es_Salaam).

## orders app

### DeliveryRegion
| Field | Type | Rules |
|---|---|---|
| name | char(80), unique | case-insensitive match against checkout region |
| fee | decimal | ≥ 0 |
| is_active | bool | inactive regions use the default fee |

Default fee for unknown or inactive regions comes from the `SHOP_DEFAULT_DELIVERY_FEE` setting.

### Cart
| Field | Type | Rules |
|---|---|---|
| user | FK User, null, unique | set for logged-in customers |
| token | char(64), unique | `secrets.token_urlsafe(32)`, used by guests |
| created_at / updated_at | datetime | |

### CartItem
| Field | Type | Rules |
|---|---|---|
| cart | FK Cart (cascade) | |
| product | FK Product (cascade) | unique together with cart |
| quantity | positive int | ≥ 1, ≤ product.stock |

The price is read live from `product.price`.

### Order
| Field | Type | Rules |
|---|---|---|
| number | char(12), unique | 8 chars from `ABCDEFGHJKMNPQRSTUVWXYZ23456789` |
| user | FK User, null | |
| contact_name | char(120) | required |
| contact_phone | char(16) | E.164; local `0XXXXXXXXX` is normalised to `+255XXXXXXXXX` |
| region, district, street, notes | char/text | region and street required |
| subtotal, delivery_fee, total | decimal | total = subtotal + delivery_fee |
| status | choice | see the state machine |
| stock_released | bool | guards against releasing stock twice |
| placed_at | datetime | auto |
| paid_at, reminder_sent_at | datetime, null | |
| expires_at | datetime | placed_at + ORDER_EXPIRY_MINUTES |

Indexes: `(status, placed_at)` and `contact_phone`.

### OrderItem
`order` FK, `product` FK (SET_NULL, null), `product_name`, `unit_price`, `quantity`, `line_total`.

### OrderEvent
`order` FK, `status`, `actor` (FK User, null), `source` (`customer|admin|system|provider`), `note`,
`created_at`.

### Order state machine

```
awaiting_payment ─► paid ─► processing ─► out_for_delivery ─► delivered
       │  │  │       │          │                │
       │  │  └► needs_review ◄──┘(late/mismatch) │
       │  └► expired ──► needs_review            │
       └► cancelled ◄──────── paid/processing/out_for_delivery/needs_review
needs_review ─► paid | cancelled
```

| From | Allowed to |
|---|---|
| awaiting_payment | paid, cancelled, expired, needs_review |
| paid | processing, cancelled, needs_review |
| processing | out_for_delivery, cancelled |
| out_for_delivery | delivered, cancelled |
| needs_review | paid, cancelled |
| expired | needs_review |
| delivered, cancelled | — (final) |

Moving to `cancelled` or `expired` releases stock if `stock_released` is false.

## payments app

### Payment
| Field | Type | Rules |
|---|---|---|
| order | FK Order (cascade) | |
| reference | char(20), unique | `<order.number>P<n>`, sent as ClickPesa `orderReference` |
| amount, currency | decimal, char(3) | amount = order.total at creation; currency TZS |
| status | choice | `pending`, `success`, `failed`, `mismatch` |
| checkout_link | URL(500), blank | |
| provider_ref | char(100), blank | ClickPesa `paymentReference` or `id` |
| channel | char(60), blank | e.g. `TIGO-PESA` |
| collected_amount | decimal, null | |
| raw_payload | JSON | last provider data (webhook + query) |
| created_at / updated_at | datetime | |

Transitions: pending → success | failed | mismatch. A success is final: later events are ignored,
which makes processing idempotent. A failed payment can still become success, because a retry can
reuse the same reference.
