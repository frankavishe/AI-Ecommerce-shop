# Contract: Web routes and BFF endpoints

The upstream API contract is `specs/001-commerce-checkout/contracts/api.md` plus the generated
OpenAPI schema (`web/openapi.yml`). This file pins what the web app itself exposes.

## BFF (same-origin JSON, consumed only by the web client)

| Method | Path | Behaviour |
|---|---|---|
| ANY | `/api/backend/{...path}` | Forwards to `${DJANGO_API_URL}/api/{path}` with the query string, body (JSON or multipart, streamed) and `Content-Type`. Adds `Authorization: Bearer <sa_access>` and `X-Cart-Token: <sa_cart>`. On a 401 with `sa_refresh` present, refreshes once and retries. If the refresh fails, it clears the auth cookies and returns the 401. When anonymous and the JSON response has a string `token` at top level (cart shape), it sets `sa_cart`. The upstream status and body pass through. Hop-by-hop headers and `Set-Cookie` from upstream are dropped. Paths beginning `auth/login`, `auth/refresh` or `auth/register` are refused (404); use `/api/session/*`. |
| POST | `/api/session/login` | `{username, password}` → upstream `auth/login/`. On 200: set `sa_access` and `sa_refresh`, merge the guest cart (`cart/merge/` with `{cart_token}`) if `sa_cart` exists, then clear `sa_cart`. Returns `{user}` (from `auth/me/`). On 401 it returns `{detail}` with one generic message. |
| POST | `/api/session/register` | Register fields → upstream `auth/register/`, then the same as login. Returns 201 `{user}` or 400 field errors. |
| POST | `/api/session/logout` | Clears `sa_access`, `sa_refresh` and `sa_cart`. Returns 204. |
| GET | `/api/session` | `{user}` from `auth/me/` (with refresh), or `{user: null}`. |
| POST | `/api/lang` | `{lang: "en"|"sw"}` → sets `sa_lang`. Returns 204. |

## Pages

| Path | Access | Notes |
|---|---|---|
| `/` | public | Categories + newest products (RSC) |
| `/products` | public | Query params as in data-model `CatalogQuery` |
| `/products/[slug]` | public | 404 page for unknown or inactive products |
| `/cart` | public | |
| `/checkout` | public | Redirects to `/cart` when the cart is empty |
| `/orders/[number]` | owner or guest proof | Guest without proof → redirect to `/track?number=` |
| `/orders/return` | public | Card return: redirect to the last order (R9) |
| `/track` | public | Number + phone lookup |
| `/login`, `/register` | public | `?next=` honoured (same-origin paths only) |
| `/account`, `/account/addresses`, `/account/orders` | logged in | proxy → `/login?next=` |
| `/admin`, `/admin/products[/new|/[slug]]`, `/admin/categories`, `/admin/orders[/[number]]`, `/admin/delivery-regions` | role admin | proxy → `/login?next=` or `/forbidden` |
| `/forbidden` | public | Access-denied page |
