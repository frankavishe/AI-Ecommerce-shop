# Research: 002 Web Storefront

## R1. Framework version
- **Decision**: Next.js 16 (latest stable, 16.4.x), App Router, TypeScript, React 19, Tailwind CSS 4, scaffolded with `create-next-app` into `web/` (`src/` dir, `@/*` alias, ESLint).
- **Rationale**: The constitution names Next.js App Router + TypeScript. 16 is current stable, so starting on 15 would mean an immediate migration. In 16, request-time route guarding lives in `src/proxy.ts`, which replaces `middleware.ts`.
- **Alternatives**: Next 15 (the seed plan said 15; rejected as outdated). Pages Router (legacy).

## R2. Talking to Django: a backend-for-frontend (BFF) proxy
- **Decision**: The browser only calls same-origin `/api/backend/<path>`, served by a catch-all route handler that forwards to `DJANGO_API_URL/api/<path>`. Along the way the handler:
  - reads the httpOnly cookies `sa_access`, `sa_refresh` and `sa_cart`, and attaches `Authorization: Bearer` and `X-Cart-Token`;
  - on a 401 with a refresh cookie, calls `auth/refresh/` once, retries, and rewrites the cookies;
  - when a response body has a cart `token` and the user is anonymous, stores it in `sa_cart`;
  - streams multipart bodies through unchanged (product image upload);
  - passes status and JSON through unchanged.
  
  Login, register and logout are dedicated route handlers under `/api/session/*` (login → set cookies → `cart/merge/` with the guest token → clear `sa_cart`).
- **Rationale**: FR-015 requires that page scripts can't read tokens. It also avoids CORS and keeps one place for refresh logic.
- **Alternatives**: localStorage JWT (fails FR-015); NextAuth (heavy for simple JWT credentials, and still needs a custom refresh); direct CORS calls (tokens exposed).

## R3. Server-rendered catalog
- **Decision**: Catalog pages (home, product list, product detail) are React Server Components that fetch Django directly (`DJANGO_API_URL`) with `next: { revalidate: 60 }` and no auth headers, so they always see the public serializer. Cart, checkout, account and admin are client components using TanStack Query against the BFF.
- **Rationale**: SC-003 (fast first paint) plus SEO for product pages. Public data needs no cookies.
- **Alternatives**: Everything client-side (slower first paint, no SEO).

## R4. API types
- **Decision**: `openapi-typescript` generates `web/src/lib/api/schema.d.ts` from a committed snapshot `web/openapi.yml`. `npm run gen:api` regenerates it, and the snapshot is refreshed with `python manage.py spectacular --file ../web/openapi.yml`. `openapi-fetch` provides typed `GET/POST/...` calls with `baseUrl` `/api/backend` (client) or `DJANGO_API_URL/api` (server).
- **Rationale**: Principle VII: the OpenAPI schema is the contract. A committed snapshot lets the web build without a running backend.
- **Alternatives**: Hand-written types (drift); orval/codegen'd hooks (more tooling than needed).

## R5. Route protection
- **Decision**: `src/proxy.ts` matches `/admin/:path*` and `/account/:path*`. It decodes (does not verify) the role claim from `sa_access`, falling back to `sa_refresh` presence for customers. It redirects to `/login?next=…` when there's no session, and to `/forbidden` when the role isn't admin. This is a UX guard only: Django enforces permissions on every call (Principle V), and the BFF never adds privileges.
- **Rationale**: Fast redirects without a round trip. Security stays server-side.

## R6. Internationalisation (FR-023)
- **Decision**: No i18n library. `src/i18n/{en,sw}.ts` are typed dictionaries (`sw` must satisfy `typeof en`, so a missing key fails type-check). The locale comes from cookie `sa_lang` (default `sw` when `Accept-Language` prefers Swahili, else `en`), and a `LanguageSwitch` sets the cookie and refreshes. Server components use `getDictionary()`; client components use a `useT()` context hook. Product `description_sw` and category `name_sw` are shown when the locale is `sw` and the value is non-empty. Admin is English-only.
- **Rationale**: Two languages and a few hundred strings. Typed dictionaries give the "no untranslated strings" check (SC-006) for free, with no URL-prefix routing.
- **Alternatives**: next-intl (fine, but adds routing/middleware complexity for 2 locales); `[locale]` URL segments (rejected: links shared on WhatsApp should stay language-neutral).

## R7. Order status freshness (FR-010, SC-002)
- **Decision**: The TanStack Query `refetchInterval` is 5 s while status is `awaiting_payment`. It stops otherwise, and also on hidden tabs (default).
- **Rationale**: Simple, and meets the 10 s target. No push channel exists yet.
- **Alternatives**: SSE/WebSocket (no backend support; overkill).

## R8. Guest order ownership on the order page
- **Decision**: After guest checkout or lookup, keep `{number, phone}` in `sessionStorage`. The guest order page gets data via `POST orders/lookup/` (number + phone) and pays via `POST orders/<n>/pay/` with `{phone}`. Logged-in owners use `GET orders/<n>/`.
- **Rationale**: Matches the backend's guest proof (Principle V). Nothing secret persists beyond the tab session.

## R9. Card payment return
- **Decision**: Stakaba's card create call has no return-URL field in our client. The checkout opens the hosted page in the same tab after saving the order number in sessionStorage. When the shopper comes back, `/orders/<n>` and `/track` show the current status. Configuring a return URL in the Stakaba dashboard (`<site>/orders/return`) is an ops task. `/orders/return` reads the saved number and redirects.
- **Rationale**: Works without backend changes.

## R10. UI kit and forms
- **Decision**: Tailwind 4 + shadcn/ui components (button, input, select, dialog, table, badge, sheet, toast via sonner) copied into `src/components/ui`. Forms use react-hook-form + zod for client-side shape checks only. Server field errors are mapped back onto fields via `setError`.
- **Rationale**: Accessible primitives without a heavy component library. Server validation remains authoritative.

## R11. Testing
- **Decision**: Vitest (+ Testing Library, jsdom) for units: money formatting, JWT role decode, BFF cookie/refresh logic with mocked `fetch`, dictionary parity, error mapping. Playwright for end-to-end runs against a local Django on port 8000 with seeded data (management command or fixtures), plus the Stakaba webhook simulated with `curl` to the token URL.
- **Rationale**: Principle VI is test-first. External services are mocked in automated tests, and e2e uses the local backend with no real payments.

## R12. Images
- **Decision**: `next/image` with `remotePatterns` for the Django media host, taken from `DJANGO_MEDIA_HOST` (default `localhost:8000`). Admin uploads go through the BFF as multipart to `products/<slug>/` (`uploaded_images`) and `products/<slug>/images/`.
