# Data Model: 002 Web Storefront

The web app owns no database. All domain data comes from the 001 API (see
`specs/001-commerce-checkout/data-model.md` and the generated `web/src/lib/api/schema.d.ts`).
This file covers only the state the web layer holds itself.

## Cookies (set by the BFF, all `httpOnly`, `SameSite=Lax`, `Secure` in production, `Path=/`)

| Cookie | Value | Lifetime | Set by | Cleared by |
|---|---|---|---|---|
| `sa_access` | Django access JWT | 30 min (matches `ACCESS_TOKEN_LIFETIME`) | login, register, refresh | logout, failed refresh |
| `sa_refresh` | Django refresh JWT | refresh lifetime from simplejwt | login, register, refresh (if rotated) | logout, failed refresh |
| `sa_cart` | guest cart token | 60 days | first cart response while anonymous | login/register (after merge), logout |
| `sa_lang` | `en` or `sw` (not httpOnly; read by client too) | 1 year | language switch | — |

## Session view (derived, not stored)

`Session = { role: "customer" | "admin" | "rider", userId: number } | null`. It is decoded from the `sa_access` payload (`role`, `user_id`) by `lib/auth.ts`. It is used for UI only (navigation, proxy redirects).

## sessionStorage (per tab)

| Key | Value | Purpose |
|---|---|---|
| `sa_guest_orders` | `{ [number]: phone }` | Guest proof for `orders/lookup/` and `orders/<n>/pay/` (R8) |
| `sa_last_order` | order number | Return target after the hosted card checkout (R9) |

## Client view models

- **Money**: API decimal strings (`"45000.00"`) → `formatTZS(s)` → `"TSh 45,000"`. Strings are never summed client-side (FR-005).
- **ApiError**: `{ status, code?, detail?, fields?: Record<string, string[]> }`, normalised from `{detail, code}` or DRF field errors by `lib/api/errors.ts`.
- **Order status display**: status → `{label (i18n key), tone}` for
  `awaiting_payment, paid, processing, out_for_delivery, delivered, cancelled, expired, needs_review` (labels in both dictionaries). "Pay again" is shown only for `awaiting_payment`. Polling runs only for `awaiting_payment` (R7).
- **CatalogQuery**: `{ search?, category?, min_price?, max_price?, in_stock?, ordering?, page? }`. This is serialised to and from URL search params exactly as the API names them (FR-002).

## Validation (client-side, advisory only; the server decides)

- Checkout: `contact_name` 1–120 chars; `contact_phone` matches `^(\+?255|0)[67]\d{8}$` after removing spaces; `region` is one of the delivery regions; `street` 1–255 chars; `email` is required when `payment_method = card`; `network` is one of `Mpesa | AirtelMoney | TigoPesa | HaloPesa` or empty (auto).
- Register: `username` required; `password` at least 8 chars; email format.
- Admin product: `price > 0`; `compare_at_price` empty or greater than price; `stock` ≥ 0 integer.
