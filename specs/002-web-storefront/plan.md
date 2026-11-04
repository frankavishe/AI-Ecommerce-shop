# Implementation Plan: Web Storefront, Checkout, Account and Admin

**Branch**: `002-web-storefront` | **Date**: 2026-11-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-web-storefront/spec.md`

## Summary

Build the Next.js web client in `web/` against the finished 001 API. Catalog pages are server-rendered from Django. Cart, checkout, account and admin are client components using TanStack Query through a same-origin BFF route handler. The BFF holds JWTs and the guest cart token in httpOnly cookies, refreshes tokens, and merges the guest cart at login. Types come from the committed OpenAPI snapshot. Customer pages are in English and Swahili through typed dictionaries. `src/proxy.ts` handles UX-level route guarding, while Django still enforces every permission.

## Technical Context

**Language/Version**: TypeScript 5, Node 24, Next.js 16.4 (App Router), React 19

**Primary Dependencies**: Tailwind CSS 4, shadcn/ui (Radix), @tanstack/react-query 5, openapi-fetch, openapi-typescript (dev), react-hook-form + zod, sonner, lucide-react

**Storage**: none in the web app. Cookies and sessionStorage only (see data-model.md). All data comes from the 001 Django API.

**Testing**: Vitest + @testing-library/react (jsdom) for units; Playwright for e2e against a local backend

**Target Platform**: Node server (`next start`) in Docker next to the Django stack; modern mobile and desktop browsers

**Project Type**: web application (frontend for the existing `backend/`)

**Performance Goals**: catalog pages show content in under 2 s on 4G (SC-003); order page reflects payment in 10 s or less (SC-002)

**Constraints**: tokens never exposed to JS (FR-015); no client price maths (FR-005); 360 px layouts (FR-024); en + sw customer UI (FR-023)

**Scale/Scope**: about 20 routes, 3 user stories, a small shop's traffic

## Constitution Check

| Principle | How this plan complies | Status |
|---|---|---|
| I. Tanzania-first | TZS formatting from decimal strings (no floats in maths); sw/en customer UI with typed dictionaries; phone hints use `+255` | ✅ |
| II. Server is truth | Shows only server totals; sends no prices; checkout body has only contact, address and payment choice | ✅ |
| III. Self-hosted AI / payment rails | No AI. Payments go through the backend's Stakaba integration. The constitution still names ClickPesa; see Complexity Tracking | ⚠️ inherited |
| IV. Verified integrations | No new inbound webhooks in the web app | ✅ n/a |
| V. Server-side roles | `proxy.ts` is UX only; Django checks every request; the BFF never elevates; guest proof is number + phone | ✅ |
| VI. Test-first | Vitest units and Playwright journeys written before each story's UI; the backend is real in e2e but payments are simulated through the webhook | ✅ |
| VII. API-first | Types generated from the drf-spectacular schema snapshot; no backend changes planned | ✅ |

Post-design re-check: unchanged. The only deviation is the inherited ClickPesa → Stakaba wording.

## Project Structure

### Documentation (this feature)

```text
specs/002-web-storefront/
├── plan.md  research.md  data-model.md  quickstart.md
├── contracts/web-routes.md
├── checklists/requirements.md
└── tasks.md            # /speckit-tasks
```

### Source Code

```text
web/
├── openapi.yml                     # schema snapshot from backend (manage.py spectacular)
├── next.config.ts  package.json  tsconfig.json  vitest.config.ts  playwright.config.ts
├── Dockerfile  .env.example
├── e2e/                            # Playwright specs + seed helper
└── src/
    ├── proxy.ts                    # route guard (/admin, /account)
    ├── app/
    │   ├── layout.tsx  providers.tsx  not-found.tsx  error.tsx  forbidden/
    │   ├── (shop)/                 # header, cart badge, lang switch
    │   │   ├── page.tsx  products/  products/[slug]/  cart/  checkout/
    │   │   ├── orders/[number]/  orders/return/  track/  login/  register/
    │   │   └── account/ (page, addresses, orders)
    │   ├── admin/                  # sidebar layout; products, categories, orders, delivery-regions
    │   └── api/
    │       ├── backend/[...path]/route.ts
    │       ├── session/{route.ts,login,register,logout}/route.ts
    │       └── lang/route.ts
    ├── components/  ui/ (shadcn)  shop/  admin/
    ├── i18n/  en.ts  sw.ts  index.ts (getDictionary, useT)
    └── lib/
        ├── api/  schema.d.ts  client.ts  server.ts  errors.ts
        ├── bff.ts                  # pure forwarding/cookie/refresh logic (unit-tested)
        ├── auth.ts  money.ts  order-status.ts  guest-orders.ts
        └── queries/  cart.ts  orders.ts  admin.ts
```

**Structure Decision**: a frontend project in `web/` next to `backend/`, matching the monorepo layout in the master plan. `infra/docker-compose.yml` gains a `web` service. Root `.gitignore` gains `backend/celerybeat-schedule*` and Playwright output folders.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Constitution III/IV still name ClickPesa and require signed webhooks + status re-query; payments now use Stakaba with token-URL webhooks | Inherited from the 2026-11-02 provider switch (not introduced here); Stakaba has no signatures, and its status API is Bearer-only | An amendment via `/speckit-constitution` is the right fix and is tracked as a follow-up. Blocking the web UI on it adds no safety, because the web never touches payment confirmation |
