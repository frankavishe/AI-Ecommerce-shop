# Implementation Plan: Delivery and Riders

**Branch**: `005-delivery-riders` | **Date**: 2026-11-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-delivery-riders/spec.md`

## Summary

A new Django app, `backend/apps/delivery`, adds the delivery job between "paid" and "delivered".

- **Jobs**: an `OrderEvent(paid)` receiver creates exactly one `Delivery` per order (a one-to-one field). One locked service, `change()`, moves it through the waiting → assigned → picked up → on the way → delivered / failed states. That service records each step in `DeliveryEvent` and drives the existing order statuses through `orders.services.transition()`, so the 001–004 order timeline and notifications keep working unchanged (R2–R4).
- **Admins**: they assign, reassign, retry and auto-assign from new Next.js admin pages, and manage riders through the extended `RiderViewSet` (regions, deactivation, welcome resend).
- **Riders**: they work entirely on WhatsApp. A resolver hook in the 004 pipeline recognises an active rider's number. The pipeline then calls the 003 agent with `role="rider"`, which offers only four rider tools, each scoped to the rider's own jobs on the server (R5, R6).
- **Messages**: riders get approved templates (welcome, assigned, removed, cancelled) plus API-only inbox entries. Customers of WhatsApp-placed orders get the rider's name and phone in the "on the way" message, and one "couldn't deliver" message per failed attempt (R7).
- **Customer web**: the order and track pages show the delivery steps (R12).
- **Set password**: a single-use 72-hour link lets riders set a password, ready for the Phase 7 app (R10).

## Technical Context

**Language/Version**: Python 3.14 (`backend/.venv`), Django 5.2, DRF 3.16. TypeScript / Next.js (admin pages, order timeline, set-password page).

**Primary Dependencies**: all existing — Celery + Redis, drf-spectacular, `httpx` through `whatsapp.graph`, the 003 OpenAI-compatible clients, and TanStack Query on the web. Django's `PasswordResetTokenGenerator` provides the setup links. No new packages.

**Storage**: PostgreSQL 16. New `delivery_*` tables, plus the `RiderProfile.regions` M2M and two datetime fields. There's a data migration from `zone` text to regions.

**Testing**: pytest + pytest-django with the 003 fake models (scripted rider tool calls), `FakeGraph` and `FakeSpeech`. The `sandbox` marker covers real template sends. The web has vitest (timeline merge, set-password form) and one Playwright spec (admin assign).

**Target Platform**: Linux containers (app box + GPU box). Windows dev uses CPU models and the WhatsApp simulator.

**Project Type**: web service (existing Django monolith) + web admin and shop UI additions.

**Performance Goals**:
- A delivery exists less than 1 minute after payment (SC-001). The rider's job message is queued on commit and sent within 1 minute (SC-003).
- Admin list pages load in under 1 s for 1,000 deliveries (indexed `(status, created_at)`).
- Rider assistant turns have the same targets as 004 text turns on the GPU model.

**Constraints**:
- Order statuses change only through `orders.services.transition()`.
- Rider tools never take a rider id or a price from the model.
- Templates are only for proactive rider and customer messages.
- Changes to 003 and 004 are additive keyword arguments and extension lists.
- Customer WhatsApp messages stay limited to WhatsApp-placed orders (004 R14).

**Scale/Scope**: one shop, 1–20 riders and tens to low hundreds of deliveries a day at launch.

## Constitution Check

*Checked against constitution v2.0.0 before research, and again after the design.*

| Principle | How this plan complies | Status |
|---|---|---|
| I. Tanzania-first | Rider phones are stored in E.164. Every fixed text, template, prompt and web label exists in sw and en, with Swahili as the default. Vehicle types include bodaboda and bajaji. | ✅ |
| II. Server is source of truth | No prices are involved. Statuses change only through the locked `change()` → `transition()` path (R4, R9). Rider tools read order data from the DB, and the model can't name a rider or price. | ✅ |
| III. Self-hosted AI, Stakaba | The rider assistant is the same 003 agent on self-hosted models. Customer notes and addresses are passed as wrapped data (FR-026). No payment changes. | ✅ |
| IV. Verified, idempotent integrations | Inbound WhatsApp uses the 004 signed webhook, unchanged. Duplicates are blocked by the delivery one-to-one, the unique `DeliveryNotification(delivery, rider, kind, attempt)` and the existing `(order, status)` notification. A repeated rider status is a no-op. Template names and `WEB_BASE_URL` come from `.env`. | ✅ |
| V. Server-side roles | The admin API uses `IsShopAdmin`, the inbox uses `IsRider`, and rider tools filter by `rider=ctx.user`. The customer `delivery` block hides rider ids, phone and notes. A deactivated rider loses the rider role on WhatsApp immediately (R6). | ✅ |
| VI. Test-first | Tests come first for each story. Graph, the models and speech are faked. Failure paths are listed in R15: replay, stale assign, wrong rider, a backwards move, a deactivated number, rider STOP, the welcome failing, a bad token, deactivation with open jobs, and duplicate notifications. | ✅ |
| VII. API-first monolith | One new app. All endpoints are in drf-spectacular, and the web types are regenerated. No new services or processes. | ✅ |

Post-design re-check (after data-model and contracts): no violations. One behaviour change to existing code is recorded below: the admin order-status guard.

## Project Structure

### Documentation (this feature)

```text
specs/005-delivery-riders/
├── plan.md
├── research.md                  # R1–R15
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── admin-api.md             # deliveries, settings, riders (extended)
│   ├── rider-tools.md           # rider role tools + prompt + fixed texts
│   ├── notifications.md         # rider/customer templates, overrides hook, rider inbox API
│   └── customer-and-account.md  # order.delivery block, set-password API + page
├── checklists/requirements.md
└── tasks.md                     # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── apps/delivery/
│   ├── apps.py                 # ready(): signals, rider tools, whatsapp hooks, template override
│   ├── models.py               # Delivery, DeliveryEvent, DeliveryNotification, RiderInboxEntry, DeliverySettings
│   ├── migrations/0001_initial.py   # + DeliverySettings row
│   ├── services.py             # change(), assign/unassign/retry, create_for_order(), choose_rider()
│   ├── signals.py              # OrderEvent receiver: paid → create (+auto-assign), cancelled → cancel
│   ├── riders.py               # rider_for_contact(), open_jobs(), deactivate guard, welcome()
│   ├── rider_tools.py          # my_jobs, job_details, update_delivery, set_availability (role rider)
│   ├── notifications.py        # rider templates, customer_failed, inbox entries, on-the-way override
│   ├── texts.py                # sw/en fixed texts (rider_stop, inbox titles)
│   ├── views.py · serializers.py · urls.py · admin.py
│   ├── management/commands/delivery_rider_eval.py
│   ├── eval/rider_cases.json
│   └── tests/                  # test_lifecycle, test_order_sync, test_admin_api, test_rider_tools,
│                               # test_rider_routing, test_notifications, test_auto_assign, test_inbox,
│                               # test_customer_view, test_concurrency
├── apps/accounts/
│   ├── models.py               # RiderProfile.regions, last_assigned_at, welcome_sent_at (+ data migration)
│   ├── serializers.py          # RiderSerializer: regions, preferred_language, is_active, welcome, convert_user
│   ├── views.py                # RiderViewSet: soft delete, resend_welcome; SetPasswordView
│   ├── tokens.py               # RiderSetupTokenGenerator (72 h)
│   └── urls.py                 # set-password/
├── apps/ai/
│   ├── tools.py                # RIDER role constant
│   ├── agent.py                # handle_message(..., role=None)
│   └── prompts.py              # rider system prompt (sw/en), system_prompt(..., role)
├── apps/whatsapp/
│   ├── processing.py           # ROLE_RESOLVERS, Job.rider, rider user/role passed to the agent
│   └── tasks.py                # ORDER_TEMPLATE_OVERRIDES in notify_order_status
├── apps/orders/
│   ├── serializers.py          # OrderSerializer.delivery (read-only)
│   └── views.py                # admin status guard: use_deliveries
├── config/settings.py          # INSTALLED_APPS, WEB_BASE_URL, RIDER_SETUP_TOKEN_HOURS,
│                               # DELIVERY_WAITING_ALERT_MINUTES, WHATSAPP_TEMPLATE_* (6 new), throttle set_password
└── config/urls.py              # path("api/", include("apps.delivery.urls"))
.env.example                    # new settings
web/src/
├── app/admin/deliveries/       # page.tsx (list + auto-assign switch), [id]/ (detail, assign dialog, actions)
├── app/admin/riders/           # page.tsx, [id]/, new/ (rider form)
├── app/admin/admin-nav.tsx     # + Deliveries, Riders
├── app/admin/orders/[number]/order-detail.tsx   # link to delivery, create-delivery button
├── app/(shop)/set-password/    # page.tsx + form
├── components/shop/order-timeline.tsx           # merge delivery events
├── lib/queries/delivery.ts     # admin deliveries/riders hooks via bff
├── lib/api/schema.d.ts         # regenerated
└── i18n/{sw,en}.ts             # admin.deliveries.*, admin.riders.*, order.delivery.*, setPassword.*
web/e2e/admin-deliveries.spec.ts
```

**Structure Decision**: one new backend app, `apps/delivery`, laid out like `apps/whatsapp` (models, services, signals, tasks, extension hooks registered in `ready()`). Other apps get small additive hooks (R1). The web adds admin sections next to orders and products, plus one public account page.

## Implementation notes

- **Reuse**:
  - **orders**: `orders.services.transition`, `InvalidTransition`, `OrderEvent` signals pattern (`whatsapp/notifications.py`), `normalize_phone`
  - **whatsapp**: `whatsapp.outbound.queue_template`/`flush`, `WhatsAppContact`, `FakeGraph`, `whatsapp_simulate`
  - **ai**: `ai.tools.register`/`run_tool`/`tools_for`, `prompts.wrap_data`, `ai.testing` fake models
  - **accounts**: `accounts.permissions.IsShopAdmin`/`IsRider`, the existing `RiderViewSet`/`RiderSerializer`
  - **web**: admin list/detail components from `admin/orders`, `components/shop/order-timeline.tsx`
- **Lock and transaction**: `change()` is `transaction.atomic()` + `select_for_update()` on the delivery row, then `transition()` on the order. Notifications are queued with `transaction.on_commit`. The order row is locked by `transition()` only through its own save; there are no nested long transactions.
- **Signal ordering**: the delivery `OrderEvent` receiver uses `dispatch_uid="delivery.order_event"`. It only reacts to `paid` and `cancelled`, so it never fires on statuses that delivery itself produces (R4).
- **Rider contact creation**: `WhatsAppContact.objects.get_or_create(phone=e164, defaults={"wa_id": digits, "language": user.preferred_language})`. If a contact exists linked to a different user, it's left unlinked and still used for sends.
- **Agent role**: `handle_message(role="rider")` builds `ToolContext(role=RIDER, user=rider)`. Rider conversations keep `channel=whatsapp`, and the 003 admin conversation list shows them with a "rider" badge (a serializer field, additive).
- **Story order**:
  - **MVP**: US1 (models, signals, change(), admin assign API + web, rider job templates) and US2 (routing, rider tools, prompt).
  - **After the MVP**: US3 (customer block, timeline, on-the-way override, failed message), US4 (rider admin + welcome + set-password) and US5 (retry, auto-assign).
  - US3, US4 and US5 can run in parallel once `change()` exists. US4's API exists in part today, so the MVP can use seeded riders.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Admin order-status action refuses `out_for_delivery` / `delivered` once a delivery exists (a behaviour change in 001/002 code) | Two writers to the same status would let the order say "delivered" while the delivery says "assigned" (FR-004) | Syncing the delivery from manual order changes would invent rider events that never happened. The guard is one check with a clear 409 `use_deliveries`, and the admin page links to the delivery. |
| Small additive hooks in 003/004 (`role=` keyword, `ROLE_RESOLVERS`, `ORDER_TEMPLATE_OVERRIDES`) | Rider routing and the rider-aware customer message need entry points inside the agent and the WhatsApp pipeline | Forking the agent loop or the pipeline for riders would duplicate the voice, rate-limit, takeover and fallback logic. Customer behaviour and the existing tests stay unchanged. |
