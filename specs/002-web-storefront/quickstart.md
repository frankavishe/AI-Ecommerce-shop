# Quickstart: 002 Web Storefront

## Prerequisites
- Node 24 / npm 11.
- The backend running locally on `http://localhost:8000`. See the 001 quickstart for the backend; the test DB setup is in project memory. Seed data: at least 2 categories, 6 active products with images, 1 product with stock 0, 2 delivery regions, a customer and an admin user.
- `web/.env.local`:
  ```
  DJANGO_API_URL=http://localhost:8000
  DJANGO_MEDIA_HOST=localhost:8000
  ```

## Run
```bash
cd web
npm install
npm run gen:api        # regenerate types from web/openapi.yml (no diff expected)
npm run dev            # http://localhost:3000
```
Refresh the schema snapshot after backend API changes:
`cd backend && python manage.py spectacular --file ../web/openapi.yml --validate`

## Automated checks
```bash
npm run lint
npm run typecheck      # tsc --noEmit (also catches missing Swahili keys)
npm test               # vitest
npm run build          # needs a reachable backend: `/` is prerendered with live catalog data
npx playwright test    # starts its own isolated stack; needs the test DB on :5434
```

## Manual validation scenarios
1. **Guest mobile money (US1)**: switch to Swahili and confirm the labels change. Search for a product, add 2 to the cart, reload, and confirm the cart persists. Check out with a `+25575…` phone, leaving network on Auto, and confirm you land on `/orders/<n>` with the "approve the prompt" notice. Simulate the payment:
   `curl -X POST http://localhost:8000/api/payments/stakaba/webhook/<STAKABA_WEBHOOK_TOKEN>/ -H "Content-Type: application/json" -d '{"internalReference":"<ref>","status":"SUCCESS","grossAmount":<total>,"currency":"TZS"}'`
   The page should show "Paid" within 10 s.
2. **Card (US1)**: check out with Card and no email → field error. Add an email and submit → the browser goes to the Stakaba hosted page (sandbox key).
3. **Account (US2)**: add an item as a guest, register, and confirm the cart still has the item. Add an address in `/account/addresses`, check out with it, and confirm the order is listed in `/account/orders`. Log out, then open `/track` and enter the order number and phone → order shown. Wrong phone → generic not-found.
4. **Admin (US3)**: as a customer, `/admin` → `/forbidden`. As an admin, create a product with 2 images → visible at `/products/<slug>`. Deactivate it → 404 on the storefront. Open a paid order, move it to `processing` with a note → shown in history. Try `cancelled → paid` → error shown and the order is unchanged.
5. **Phone layout**: in devtools at 360 px wide, home → checkout has no horizontal scroll.
