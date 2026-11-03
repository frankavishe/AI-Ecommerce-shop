# Tasks: Web Storefront, Checkout, Account and Admin

**Input**: Design documents from `specs/002-web-storefront/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/web-routes.md, quickstart.md

**Tests**: required (Constitution VI). Each story's tests come before its UI. All paths are relative to the repo root.

## Phase 1: Setup

- [X] T001 Scaffold `web/` with `npx create-next-app@16 web --ts --tailwind --eslint --app --src-dir --import-alias "@/*" --use-npm --no-turbopack`. Then add deps `@tanstack/react-query openapi-fetch react-hook-form zod @hookform/resolvers sonner lucide-react clsx tailwind-merge` and dev deps `openapi-typescript vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/jest-dom @playwright/test`
- [X] T002 Add scripts to `web/package.json`: `typecheck` (tsc --noEmit), `test` (vitest run), `gen:api` (openapi-typescript openapi.yml -o src/lib/api/schema.d.ts), `e2e` (playwright test). Add `web/vitest.config.ts` (jsdom, `@` alias, setup file `src/test/setup.ts`) and `web/playwright.config.ts` (baseURL http://localhost:3000, webServer `npm run dev`)
- [X] T003 [P] Initialise shadcn/ui (`npx shadcn@latest init`) and add button, input, label, select, textarea, dialog, sheet, table, badge, card, skeleton, radio-group, checkbox, dropdown-menu, sonner into `web/src/components/ui/`
- [X] T004 [P] Generate `web/openapi.yml` with `python manage.py spectacular --file ../web/openapi.yml --validate` (from `backend/`), then run `npm run gen:api` to produce `web/src/lib/api/schema.d.ts`
- [X] T005 [P] Create `web/.env.example` (`DJANGO_API_URL=http://localhost:8000`, `DJANGO_MEDIA_HOST=localhost:8000`) and `web/next.config.ts` with `images.remotePatterns` built from `DJANGO_MEDIA_HOST` (http and https, path `/media/**`). Add `backend/celerybeat-schedule*`, `web/test-results/`, `web/playwright-report/` to root `.gitignore`
- [X] T006 [P] Add a `web` service to `infra/docker-compose.yml` (image node:24-alpine, working_dir /app, volume `../web:/app`, command `sh -c "npm ci && npm run dev"`, env `DJANGO_API_URL=http://api:8000`, `DJANGO_MEDIA_HOST=localhost:8000`, port 3000, depends_on api). Add `web/Dockerfile` (multi-stage `next build` + `next start`)

## Phase 2: Foundational (blocks all stories)

- [X] T007 [P] Tests `web/src/lib/money.test.ts`: `formatTZS("45000.00")` → `"TSh 45,000"`, `"1234.50"` → `"TSh 1,234.50"`, `"0.00"` → `"TSh 0"`; never uses float addition
- [X] T008 [P] Tests `web/src/lib/auth.test.ts`: `decodeSession(token)` returns `{role, userId}` from a JWT payload (`role`, `user_id`); returns null for malformed tokens; `isExpired` with a 30 s skew
- [X] T009 [P] Tests `web/src/lib/bff.test.ts` (mocked fetch), per contracts/web-routes.md:
  - forwards path, query, method, JSON and multipart bodies;
  - adds `Authorization: Bearer <sa_access>` and `X-Cart-Token: <sa_cart>`;
  - on a 401 with `sa_refresh`, calls `auth/refresh/` once, retries and returns new cookie values (rotated refresh kept); a failed refresh clears `sa_access`/`sa_refresh` and returns the 401;
  - when anonymous, a top-level string `token` in the JSON response sets `sa_cart`;
  - drops upstream `set-cookie` and hop-by-hop headers;
  - refuses paths starting `auth/login`, `auth/refresh`, `auth/register` with 404
- [X] T010 [P] Tests `web/src/lib/api/errors.test.ts`: normalises `{detail, code}` and DRF field errors (`{field: ["msg"]}`, `non_field_errors`) into `ApiError {status, code?, detail?, fields?}`
- [X] T011 [P] Test `web/src/i18n/i18n.test.ts`: every key in `en` exists and is non-empty in `sw`, and vice versa
- [X] T012 Implement `web/src/lib/money.ts`, `web/src/lib/auth.ts` (cookie names `sa_access`, `sa_refresh`, `sa_cart`, `sa_lang`; cookie options httpOnly, SameSite=Lax, Secure in production, Path=/; lifetimes: access 30 min, refresh 30 days, cart 60 days, lang 1 year) and `web/src/lib/api/errors.ts` so T007, T008 and T010 pass
- [X] T013 Implement `web/src/lib/bff.ts` (pure `forward({method, path, search, headers, body, cookies}, fetchImpl)` → `{status, headers, body, setCookies}`) and wire it into `web/src/app/api/backend/[...path]/route.ts` for GET/POST/PUT/PATCH/DELETE so T009 passes
- [X] T014 [P] Implement `web/src/lib/api/client.ts` (openapi-fetch, baseUrl `/api/backend`, throws `ApiError`) and `web/src/lib/api/server.ts` (openapi-fetch, baseUrl `${DJANGO_API_URL}/api`, no auth, `next: {revalidate: 60}` default)
- [X] T015 [P] Implement `web/src/i18n/en.ts`, `web/src/i18n/sw.ts` (`satisfies Dictionary`), `web/src/i18n/index.ts` (`getLocale()` from `sa_lang` cookie or Accept-Language, `getDictionary()`, `I18nProvider`, `useT()`), `web/src/app/api/lang/route.ts` and `web/src/components/shop/language-switch.tsx` so T011 passes
- [X] T016 Implement `web/src/app/providers.tsx` (QueryClient, I18nProvider, Toaster), root `web/src/app/layout.tsx` (lang attr from locale), `web/src/app/error.tsx` (friendly message + retry, FR-025), `web/src/app/not-found.tsx` and `web/src/app/forbidden/page.tsx`
- [X] T017 Implement session route handlers `web/src/app/api/session/route.ts` (GET user or null), `login/route.ts`, `register/route.ts`, `logout/route.ts` per contracts/web-routes.md (login → set cookies → `cart/merge/` with `{cart_token}` when `sa_cart` → clear `sa_cart`; generic login error), reusing `lib/bff.ts`
- [X] T018 Implement `web/src/proxy.ts` guarding `/admin/:path*` (role admin, else `/forbidden`; no session → `/login?next=`) and `/account/:path*` (any session), with `?next=` limited to same-origin paths. Add tests `web/src/proxy.test.ts`
- [X] T019 [P] Add `web/e2e/seed.py` (run with `python manage.py shell < ../web/e2e/seed.py`): idempotently creates 2 categories, 6 active products with an image, 1 out-of-stock product, 2 delivery regions, customer `e2e_customer`/`e2e-pass-123`, admin `e2e_admin`/`e2e-pass-123`. Add `web/e2e/helpers.ts` (login helper, `simulatePayment(orderNumber)` that reads the payment reference via the admin API and POSTs the Stakaba webhook to `/api/payments/stakaba/webhook/<STAKABA_WEBHOOK_TOKEN>/` with `status: "SUCCESS"`, `grossAmount` = total, `currency: "TZS"`)

**Checkpoint**: `npm run typecheck && npm test` passes; `/api/backend/products/` returns products through the BFF.

## Phase 3: User Story 1 – Guest buys a product (P1) 🎯 MVP

**Goal**: browse → cart → checkout → pay (mobile money / card) → live order page, in en and sw.

**Independent Test**: `npx playwright test e2e/guest-checkout.spec.ts`

- [X] T020 [P] [US1] `web/e2e/guest-checkout.spec.ts`:
  - home shows categories and products;
  - search + category filter update the URL and the results;
  - add to cart, reload, and the cart persists;
  - quantity above stock shows the server message;
  - checkout with an invalid phone shows a field error;
  - mobile money checkout lands on `/orders/<n>` with the approve notice, then `simulatePayment` → "Paid" visible within 10 s with no reload;
  - card without email shows an email error;
  - switching language to sw changes the header and checkout labels
- [X] T021 [P] [US1] Unit tests `web/src/lib/order-status.test.ts` (status → i18n label key and tone for all 8 statuses `awaiting_payment, paid, processing, out_for_delivery, delivered, cancelled, expired, needs_review`; `canPay` only for `awaiting_payment`; `shouldPoll` only for `awaiting_payment`) and `web/src/lib/guest-orders.test.ts` (sessionStorage `sa_guest_orders` `{[number]: phone}` and `sa_last_order` get/set, tolerant of storage errors)
- [X] T022 [US1] Implement `web/src/lib/order-status.ts` and `web/src/lib/guest-orders.ts` so T021 passes
- [X] T023 [US1] Shop layout `web/src/app/(shop)/layout.tsx` with `web/src/components/shop/header.tsx` (logo, search box → `/products?search=`, cart badge from `useCart`, language switch, login/account link from `/api/session`) and footer. Responsive at 360 px
- [X] T024 [P] [US1] Cart queries `web/src/lib/queries/cart.ts`: `useCart`, `useAddItem`, `useUpdateItem`, `useRemoveItem`, `useClearCart`. Mutations replace the cart cache with the server response and show `ApiError.detail` via a toast
- [X] T025 [P] [US1] Components `web/src/components/shop/product-card.tsx` (image, name, `formatTZS` price, compare-at struck through when higher, out-of-stock badge), `price.tsx` and `pagination.tsx`
- [X] T026 [US1] Home `web/src/app/(shop)/page.tsx` (RSC: `categories/` + `products/?ordering=-created_at`, first 8) and catalog `web/src/app/(shop)/products/page.tsx` (RSC reading `search, category, min_price, max_price, in_stock, ordering, page`; filter sidebar/sheet as a client component writing URL params; empty state)
- [X] T027 [US1] Product page `web/src/app/(shop)/products/[slug]/page.tsx` (RSC, `notFound()` on 404, gallery, `description_sw` when locale is sw and non-empty, `generateMetadata`) with client `add-to-cart.tsx` (quantity stepper, disabled when out of stock)
- [X] T028 [US1] Cart page `web/src/app/(shop)/cart/page.tsx`: line items with quantity edit/remove, server subtotal, empty state, "Checkout" button
- [X] T029 [US1] Checkout `web/src/app/(shop)/checkout/page.tsx` + `web/src/components/shop/checkout-form.tsx` (react-hook-form + zod).
  - Fields and checks: `contact_name` 1–120 chars; `contact_phone` matching `^(\+?255|0)[67]\d{8}$` after removing spaces; region select from `delivery-regions/` showing fees; optional `district`; `street` 1–255 chars; optional `notes`.
  - Payment: radio mobile_money (default) / card; `network` select Auto, Mpesa, AirtelMoney, TigoPesa or HaloPesa (omitted when Auto); `email` required when card.
  - Server field errors are mapped with `setError`; an empty cart redirects to `/cart`.
  - On 201: store guest proof, then redirect to `payment_url` (card) or go to `/orders/<n>?pending=1`.
- [X] T030 [US1] Order page `web/src/app/(shop)/orders/[number]/page.tsx` + `web/src/components/shop/order-view.tsx` + `order-timeline.tsx` + `pay-again-dialog.tsx`.
  - Loads the order with `orders/lookup/` (guest proof) or `GET orders/<n>/` (logged in). With neither, it redirects to `/track?number=`.
  - Polls every 5 s while `awaiting_payment`.
  - Shows the approve notice when `?pending=1` and `payment_error` text when present.
  - "Pay again" calls `orders/<n>/pay/` with the method choice (and `{phone}` for guests).
- [X] T031 [US1] `web/src/app/(shop)/orders/return/page.tsx`: client redirect to `/orders/<sa_last_order>`, or to `/track` when there is none
- [X] T032 [US1] Fill every US1 string in `en.ts`/`sw.ts`; run `npm run typecheck && npm test && npx playwright test e2e/guest-checkout.spec.ts`

**Checkpoint**: MVP. Commit `feat(web): guest storefront, cart, checkout and live order page (US1)`.

## Phase 4: User Story 2 – Registered customer and tracking (P2)

**Independent Test**: `npx playwright test e2e/account.spec.ts`

- [ ] T033 [P] [US2] `web/e2e/account.spec.ts`:
  - guest adds an item → registers → the cart still has the item (merge);
  - add an address → checkout with the saved address shows the prefilled name and phone → order appears in `/account/orders`;
  - logout → `/account` redirects to `/login?next=/account`;
  - `/track` with the right phone shows the order, and a wrong phone shows the generic not-found;
  - a wrong password shows a single generic error
- [ ] T034 [US2] Login and register pages `web/src/app/(shop)/login/page.tsx`, `web/src/app/(shop)/register/page.tsx` (`username` required, `password` ≥ 8 chars, email format, phone, `preferred_language`). They post to `/api/session/*`, invalidate the session and cart queries, and redirect to `next` or `/account`
- [ ] T035 [US2] Account area `web/src/app/(shop)/account/layout.tsx` (tabs, logout button → `/api/session/logout` → clear queries → `/`), `page.tsx` (profile edit via `auth/me/` PATCH), `addresses/page.tsx` (CRUD `auth/addresses/` with dialog form), `orders/page.tsx` (paginated `orders/`, newest first, links to `/orders/<n>`)
- [ ] T036 [US2] Saved-address picker in `checkout-form.tsx` for logged-in users (sends `address_id`; name and phone prefilled from the session user)
- [ ] T037 [US2] Track page `web/src/app/(shop)/track/page.tsx`: number + phone form → `orders/lookup/`. On 200 it stores guest proof and goes to `/orders/<n>`; on 404 it shows a generic message
- [ ] T038 [US2] Fill US2 strings in both dictionaries; run typecheck, unit tests and `e2e/account.spec.ts`

**Checkpoint**: commit `feat(web): accounts, saved addresses, order history and tracking (US2)`.

## Phase 5: User Story 3 – Admin (P3)

**Independent Test**: `npx playwright test e2e/admin.spec.ts`

- [ ] T039 [P] [US3] `web/e2e/admin.spec.ts`:
  - a customer opening `/admin`, `/admin/products` or `/admin/orders` is sent to `/forbidden`; anonymous users are sent to `/login`;
  - an admin creates a product with 2 images → it is visible at `/products/<slug>`; deactivating it makes the storefront page 404;
  - a paid order moved to `processing` with a note → the note shows in history; an invalid transition shows the error and the status is unchanged;
  - a delivery region created → it appears in the checkout region select
- [ ] T040 [US3] Admin layout `web/src/app/admin/layout.tsx` (sidebar: Dashboard, Products, Categories, Orders, Delivery regions; user menu; English only) and admin queries `web/src/lib/queries/admin.ts`
- [ ] T041 [US3] Dashboard `web/src/app/admin/page.tsx`: counts via `admin/orders/?status=awaiting_payment|paid|processing` (`count` from pagination) and the `products/low_stock/` list
- [ ] T042 [US3] Products `web/src/app/admin/products/page.tsx` (table, search, category/active/in-stock filters, pagination) and `web/src/components/admin/product-form.tsx` used by `products/new/page.tsx` and `products/[slug]/page.tsx`.
  - Fields and checks: name, sku, category, description, description_sw, `price > 0`, `compare_at_price` empty or greater than price, `stock` ≥ 0 integer, low_stock_threshold, tags, is_active.
  - Create sends multipart with `uploaded_images`.
  - The image manager (`products/<slug>/images/`) supports add, alt text, position and delete.
- [ ] T043 [US3] Categories `web/src/app/admin/categories/page.tsx` (table + dialog CRUD: name, name_sw, parent, is_active)
- [ ] T044 [US3] Orders `web/src/app/admin/orders/page.tsx` (filters `status`, `paid`, `placed_after`, `placed_before`, `search`, all in URL params; pagination) and `orders/[number]/page.tsx` (items, totals, contact/delivery, events, payments table, status-change dialog posting `{status, note}` to `admin/orders/<n>/status/` and showing `invalid_transition`)
- [ ] T045 [US3] Delivery regions `web/src/app/admin/delivery-regions/page.tsx` (table + dialog CRUD: name, fee, is_active)
- [ ] T046 [US3] Run typecheck, unit tests and `e2e/admin.spec.ts`

**Checkpoint**: commit `feat(web): admin dashboard, products, categories, orders and regions (US3)`.

## Phase 6: Polish

- [ ] T047 Run `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`, the full `npx playwright test`, and `npm run gen:api` (no diff); fix any issues
- [ ] T048 [P] Walk through quickstart.md manually (including 360 px layouts in Chrome) and fix layout issues
- [ ] T049 [P] Mark tasks done in `specs/002-web-storefront/tasks.md` and update project memory

## Dependencies

- Setup → Foundational → US1 → (US2, US3 in either order). US2 extends `checkout-form.tsx` from US1, and US3 uses the shared admin queries only.
- Within a story, tests come first, then lib/queries, then pages.

## Parallel examples

- Foundational: T007–T011 (separate test files) together; T014 and T015 alongside T013.
- US1: T020 + T021; then T024 + T025.
- US3: T043 and T045 are independent pages after T040.

## Implementation Strategy

MVP = Phases 1–3 (guest purchase in en/sw). Then US2 → US3, with a commit after each story.
