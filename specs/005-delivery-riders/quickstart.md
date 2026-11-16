# Quickstart: validating Delivery and Riders (005)

These checks prove the feature end to end. Contracts: [admin-api](contracts/admin-api.md), [rider-tools](contracts/rider-tools.md), [notifications](contracts/notifications.md), [customer-and-account](contracts/customer-and-account.md). Data: [data-model](data-model.md).

## Prerequisites

- Start the test DB with `docker start ai-shop-testdb` (port 5434). See memory: pytest hangs when it's down.
- Backend venv: `backend/.venv`. Web: `npm ci` in `web/`.
- No real WhatsApp or model is needed for automated checks (`FakeGraph`, fake models).

## 1. Automated tests

From `backend/`:

```bash
DATABASE_URL=postgres://shop:shop@localhost:5434/shop .venv/Scripts/python -m pytest
DATABASE_URL=postgres://shop:shop@localhost:5434/shop .venv/Scripts/python -m pytest apps/delivery -q
```

Expected: everything is green. The 001–004 suites are unchanged in count, and the new `apps/delivery/tests/*` cover R15.

From `web/`:

```bash
npm run test && npm run lint && npm run typecheck
npx playwright test e2e/admin-deliveries.spec.ts
```

## 2. Manual flow on the simulator (no Meta account)

This uses the 004 recipe. The scratch DB `shop_sim` on port 5434 is seeded with `rag_eval --seed`, and runs with `WHATSAPP_FAKE_GRAPH=1` and `CELERY_TASK_ALWAYS_EAGER=1`.

1. **Create a rider (US4)**: `POST /api/auth/riders/` as admin, with regions `["Kinondoni"]` and phone `+255700000001`.
   - **Expect**: the log shows a `rider_welcome` template to `255700000001` with a set-password URL. Opening the URL on the web `/set-password` and setting a password returns 204. Opening it a second time shows `invalid_link`.
2. **Pay an order (US1)**: place an order for region Kinondoni and pay it with the Stakaba sandbox or the fake webhook.
   - **Expect**: `GET /api/admin/deliveries/` lists one `waiting` delivery. Replaying the webhook still gives one.
3. **Assign (US1)** from the admin web at `/admin/deliveries`.
   - **Expect**: the delivery is `assigned` and the order is `processing`. The log shows a `delivery_assigned` template to the rider, and `GET /api/rider/inbox/` as the rider shows one unread entry.
4. **Rider on WhatsApp (US2)**, with the CPU model or the GPU box:
   - `whatsapp_simulate --inline --from 255700000001 --text "kazi zangu?"` → a reply listing the order.
   - `--text "nimechukua mzigo wa <number>"` → a confirmation. The delivery is `picked_up` and the order is `out_for_delivery`. If the order was placed on WhatsApp, the customer number gets `order_on_the_way_rider` with the rider's first name and phone.
   - `--text "nimefikisha <number>"` → the delivery and the order are `delivered`. Sending it again → "already", with no second customer message.
   - From another rider's number, ask about the same order → "not found among your jobs".
5. **Failure path (US5)**: assign a new order, have the rider pick it up, then send `--text "imeshindikana, mteja hapatikani"`.
   - **Expect**: the delivery is `failed` and highlighted in the admin list. A WhatsApp-placed order's customer gets `order_delivery_failed` once. Admin "retry" then gives attempt 2, `waiting`.
6. **Auto-assign (US5)**: switch it on at `/admin/deliveries` with two available Kinondoni riders, then pay an order.
   - **Expect**: the rider with fewer active jobs is assigned automatically.
7. **Customer view (US3)**: open `/orders/<number>` or `/track`.
   - **Expect**: the timeline shows "Rider assigned (Juma, Motorbike)", "Picked up", "On the way" and "Delivered", with no rider phone or failure reason.

## 3. Rider assistant evaluation (SC-004, GPU)

```bash
python manage.py delivery_rider_eval --database shop_sim --report
```

**Expect** ≥ 90% correct tool and arguments over ≥ 30 cases. CPU results are informational only.

## 4. Before going live

- Get the 6 new templates approved by Meta in sw and en (contracts/notifications.md), and set the `WHATSAPP_TEMPLATE_*` names in `.env`.
- Set `WEB_BASE_URL` to the public shop URL.
