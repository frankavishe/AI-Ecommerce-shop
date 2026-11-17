---

description: "Task list for 005 Delivery and Riders"
---

# Tasks: Delivery and Riders

**Input**: Design documents from `specs/005-delivery-riders/`

**Prerequisites**: plan.md, spec.md, research.md (R1–R15), data-model.md, contracts/ (admin-api.md,
rider-tools.md, notifications.md, customer-and-account.md), quickstart.md

**Tests**: required (Constitution VI).
- In each story, write the tests first and confirm they fail before implementing.
- Graph, whisper and the chat model are always faked: `FakeGraph` (`apps/whatsapp/testing.py`),
  `FakeSpeech`, and the 003 fake models from `backend/conftest.py`, scripted to emit rider tool calls.
- Paths are relative to the repo root.
- Run the tests from `backend/` with
  `DATABASE_URL=postgres://shop:shop@localhost:5434/shop .venv/Scripts/python -m pytest`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on unfinished tasks)
- **[Story]**: US1–US5 from spec.md

---

## Phase 1: Setup

- [X] T001 Create the app skeleton `backend/apps/delivery/`:
  - Files: `__init__.py`; `apps.py` (`DeliveryConfig`, `name="apps.delivery"`, with a `ready()` that for now imports only `signals`); empty `models.py`, `urls.py`, `tests/__init__.py`, `management/__init__.py`, `management/commands/__init__.py`; and `eval/.gitkeep`.
  - Add `"apps.delivery"` to `INSTALLED_APPS` in `backend/config/settings.py`, after `apps.whatsapp`.
  - Add `path("api/", include("apps.delivery.urls"))` in `backend/config/urls.py`.
- [X] T002 [P] Add these settings to `backend/config/settings.py`, read from env with these defaults:
  - `WEB_BASE_URL="http://localhost:3000"`, `RIDER_SETUP_TOKEN_HOURS=72`, `DELIVERY_WAITING_ALERT_MINUTES=15`.
  - Templates:
    - `WHATSAPP_TEMPLATE_RIDER_WELCOME="rider_welcome"`
    - `WHATSAPP_TEMPLATE_DELIVERY_ASSIGNED="delivery_assigned"`
    - `WHATSAPP_TEMPLATE_DELIVERY_REMOVED="delivery_removed"`
    - `WHATSAPP_TEMPLATE_DELIVERY_CANCELLED="delivery_cancelled"`
    - `WHATSAPP_TEMPLATE_ORDER_ON_THE_WAY_RIDER="order_on_the_way_rider"`
    - `WHATSAPP_TEMPLATE_DELIVERY_FAILED="order_delivery_failed"`
  - Throttle rate `"set_password": "10/hour"`.
- [X] T003 [P] Add the T002 variables to `.env.example`, with comments. Include the suggested Swahili template bodies from `contracts/notifications.md` as a comment block.

---

## Phase 2: Foundational (blocks all stories)

**⚠️ No story work starts until this phase is done.**

### Models and migrations

- [X] T004 Write `backend/apps/delivery/models.py` exactly per `data-model.md`:
  - **`Delivery`**:
    - `order`: OneToOne → `orders.Order`, PROTECT, `related_name="delivery"`.
    - `status`: char(12), TextChoices `waiting · assigned · picked_up · on_the_way · delivered · failed · cancelled`, default `waiting`.
    - `rider`: FK → `accounts.User`, null, SET_NULL, `related_name="deliveries"`.
    - `attempt`: PositiveSmallInteger, default 1.
    - `failure_reason`: char(255), blank.
    - `assigned_at`, `picked_up_at`, `delivered_at`, `failed_at`: datetime, null.
    - `created_at`, `updated_at`.
    - Indexes `(status, created_at)` and `(rider, status)`.
    - CheckConstraint: `rider IS NOT NULL` when status ∈ {assigned, picked_up, on_the_way}.
    - Module constants `OPEN = {waiting, assigned, picked_up, on_the_way}` and `ACTIVE = {assigned, picked_up, on_the_way}`.
  - **`DeliveryEvent`**:
    - `delivery`: FK, CASCADE, `related_name="events"`.
    - `status`: char(12).
    - `attempt`: smallint.
    - `rider`: FK User, null.
    - `actor_type`: char(8), `admin · rider · system`.
    - `actor`: FK User, null.
    - `note`: char(255), blank.
    - `created_at`.
    - Ordering `created_at, id`.
  - **`DeliveryNotification`**:
    - `delivery`: FK, null.
    - `rider`: FK User, null.
    - `kind`: char(20), `rider_welcome · rider_assigned · rider_removed · rider_cancelled · customer_failed`.
    - `attempt`: smallint, default 1.
    - `outbound`: FK → `whatsapp.WhatsAppOutboundMessage`, null, SET_NULL.
    - `state`: char(8), `queued · skipped · failed`, default `queued`.
    - `created_at`.
    - Constraints: UniqueConstraint `(delivery, rider, kind, attempt)`, plus a partial unique `(rider, kind, attempt)` where `delivery IS NULL`.
  - **`RiderInboxEntry`**:
    - `rider`: FK User, CASCADE, `related_name="inbox"`.
    - `kind`: char(12), `assigned · removed · cancelled`.
    - `delivery`: FK, CASCADE.
    - `title_sw`, `title_en`: char(160).
    - `read_at`: null.
    - `created_at`.
  - **`DeliverySettings`**:
    - `auto_assign`: bool, default False.
    - `updated_at`.
    - `updated_by`: FK User, null.
    - Classmethod `get()` returns `get_or_create(pk=1)`.
- [X] T005 Create `backend/apps/delivery/migrations/0001_initial.py` with `makemigrations delivery`. Add a `RunPython` step that creates the `DeliverySettings(pk=1)` row.
- [X] T006 [P] Extend `RiderProfile` in `backend/apps/accounts/models.py`:
  - `regions`: M2M → `orders.DeliveryRegion`, `related_name="riders"`, blank.
  - `last_assigned_at`: datetime, null.
  - `welcome_sent_at`: datetime, null.
  - Keep `zone`.
  - Generate the schema migration, then add a data migration in `backend/apps/accounts/migrations/` that copies a case-insensitive `zone` match into `regions`.
- [X] T007 [P] Register `Delivery` (with an inline for `DeliveryEvent`), `DeliveryNotification`, `RiderInboxEntry` and `DeliverySettings` in `backend/apps/delivery/admin.py`. They are read-mostly.

### Core service (R4, R9)

- [X] T008 Write the foundational tests in `backend/apps/delivery/tests/test_lifecycle.py`, plus fixtures in `backend/apps/delivery/tests/conftest.py`:
  - **Fixtures**: `region` (Kinondoni); `rider` (role=rider, phone `+255700000001`, profile covering the region); `rider2`; `paid_order` (moved to paid through `orders.services.transition`); `admin_user`.
  - **Tests**:
    - Every allowed move in the data-model transition table succeeds and writes one `DeliveryEvent` with attempt, rider, actor_type and note.
    - A backwards move raises `InvalidDeliveryTransition`, and so does any move out of `delivered`/`cancelled`.
    - Repeating the current status returns `already` with no new event (assigned→assigned to the same rider counts as a repeat).
    - `failed` without a note raises `ReasonRequired`.
    - `expect` mismatch (status or rider) raises `StaleDelivery`.
    - assigned→delivered records `picked_up` then `delivered`.
    - Retry from `failed` increments `attempt` and clears rider and `failure_reason`.
    - The check constraint refuses `assigned` with no rider.
- [X] T009 Write the order-sync tests in `backend/apps/delivery/tests/test_order_sync.py`:
  - Assign moves a `paid` order to `processing` and leaves a `processing` one alone.
  - picked_up moves the order to `out_for_delivery`; on_the_way leaves it there.
  - delivered moves the order to `delivered`.
  - failed and retry leave the order unchanged.
  - Each order transition produces exactly one `OrderEvent`.
- [X] T010 Implement `backend/apps/delivery/services.py`:
  - Exceptions: `DeliveryError(code)` with subclasses `InvalidDeliveryTransition`, `StaleDelivery`, `ReasonRequired`, `RiderUnavailable`.
  - A `TRANSITIONS` table copied from data-model.md.
  - **`change(delivery, to, actor, *, actor_type, rider=None, note="", expect=None) -> Result(status, recorded: list, already: bool)`**:
    - Inside `transaction.atomic()`, re-fetch the row with `select_for_update()`.
    - Check `expect` (a dict with `status` and/or `rider`).
    - Validate the move and write the events, setting the matching `*_at` fields and `failure_reason`.
    - Bump `RiderProfile.last_assigned_at` on assign.
    - Drive `orders.services.transition(order, …, OrderEvent.Source.SYSTEM)` per R4, skipping when the order is already there.
    - Collect the notification intents (`assigned` / `removed` / `cancelled` / `customer_failed`) on the result, for the hooks in `NOTIFY_HOOKS: list` called through `transaction.on_commit`. The list stays empty until US1/US3 register senders.
  - Helpers:
    - `assign(delivery, rider, actor, expect=None)`: checks that the rider is assignable (`role=rider`, `is_active`, profile `is_available`), else `RiderUnavailable`.
    - `unassign(delivery, actor, expect=None)`.
    - `retry(delivery, actor, rider=None)`.
    - `create_for_order(order) -> (delivery, created)`: `get_or_create`.
    - `cancel_for_order(order, actor=None)`.
  - Make T008–T009 pass.
- [X] T011 [P] Write `backend/apps/delivery/riders.py`:
  - `active_riders()`: a queryset of `role=rider`, `is_active`, with a profile.
  - `assignable_riders()`: `active_riders()` filtered to `profile.is_available`.
  - `open_jobs(rider)`: a count of ACTIVE deliveries.
  - `annotate_open_jobs(qs)`.
  - `rider_for_contact(contact)`: the active rider whose `phone == contact.phone`, else None.

**Checkpoint**: `pytest apps/delivery` is green for T008–T009. The models are migrated and the 001–004 suites are still green.

---

## Phase 3: User Story 1 – Admin assigns a rider to a paid order (P1) 🎯 MVP

**Goal**: a paid order gets a waiting delivery. The admin assigns, reassigns and unassigns it from the web; the rider gets a WhatsApp job template and an inbox entry; and cancelling the order cancels the delivery.

**Independent Test**: pay an order (or call `transition` to paid) → `GET /api/admin/deliveries/` lists it as waiting → assign a rider → the delivery is assigned, the order is processing, `FakeGraph` shows a `delivery_assigned` template sent to the rider, and an inbox entry exists.

### Tests for US1 (write first; they must fail)

- [X] T012 [P] [US1] Write `backend/apps/delivery/tests/test_signals.py`:
  - An order moved to paid creates one waiting delivery.
  - Replaying `paid` (the payment webhook replay path in `apps/payments`) still leaves exactly one.
  - Moving an order with a waiting or assigned delivery to `cancelled` cancels the delivery and records a `cancelled` event with actor_type `system`.
  - Statuses that delivery itself produces (processing, out_for_delivery, delivered) don't re-enter the receiver.
- [X] T013 [P] [US1] Write `backend/apps/delivery/tests/test_admin_api.py`:
  - List: filters `status`, `region`, `rider` and `attention=1`; sort with attention first; the item shape follows `contracts/admin-api.md`.
  - Detail includes `events`, `notifications` and `failure_reason`.
  - `candidates`: region riders first, then by open jobs; inactive riders excluded; `is_available` and `covers_region` flags shown.
  - `assign`: 200 from waiting; reassign from assigned; 400 `rider_unavailable` for an unavailable or inactive rider; 409 `stale` with the current delivery in the body when `expected_status` or `expected_rider` mismatch; 409 `invalid_transition` once picked up.
  - `unassign`.
  - `status`: admin override, with `note` required for failed.
  - `POST /api/admin/orders/{number}/delivery/`: 201; 409 `exists`; 400 `not_deliverable`.
  - Customers, riders and anonymous users get 403/401 on every endpoint (FR-025).
- [X] T014 [P] [US1] Write `backend/apps/delivery/tests/test_notifications.py` (rider part):
  - Assign queues one `delivery_assigned` template to the rider's contact. Use `FakeGraph`, with the parameters order no., region, street, contact name and item count. The contact is created with `wa_id` = the digits of the E.164 number and language = `preferred_language`.
  - Reassign sends `delivery_assigned` to the new rider and `delivery_removed` to the old one.
  - Unassign sends `delivery_removed`.
  - An order cancel while assigned sends `delivery_cancelled`.
  - Each case writes one `DeliveryNotification` row and one `RiderInboxEntry` (titles in sw and en).
  - Rider sends ignore `updates_allowed=False`.
  - Replaying the same change sends nothing twice.
  - A Graph failure marks the notification/outbound row and does not roll back the delivery.
- [X] T015 [P] [US1] Write `backend/apps/delivery/tests/test_order_guard.py`. The admin order-status action (`AdminOrderViewSet`) answers 409 `use_deliveries` for `out_for_delivery` and `delivered` when the order has a delivery. `processing` and `cancelled` are still allowed. Orders without a delivery behave as before.
- [X] T016 [P] [US1] Write `backend/apps/delivery/tests/test_concurrency.py` (`transaction=True`): two threads assign the same waiting delivery with `expected_status="waiting"`; exactly one succeeds and the other gets `StaleDelivery`.

### Implementation for US1

- [X] T017 [US1] Implement `backend/apps/delivery/signals.py`. A `post_save` receiver on `orders.OrderEvent` (`dispatch_uid="delivery.order_event"`, created and not raw):
  - Status `paid`: `transaction.on_commit(create_for_order)`, then auto-assign if switched on (a stub that US5 fills).
  - Status `cancelled`: `cancel_for_order`.
  - Ignore everything else.
- [X] T018 [P] [US1] Write `backend/apps/delivery/texts.py` with sw/en fixed texts:
  - `rider_stop` (the wording in `contracts/rider-tools.md`).
  - Inbox titles `inbox_assigned` / `inbox_removed` / `inbox_cancelled`, taking `{number}`.
  - A `text(key, lang, **kw)` helper, in the same style as `apps/whatsapp/texts.py`.
- [X] T019 [US1] Implement `backend/apps/delivery/notifications.py` (rider part):
  - `rider_contact(user)`: `WhatsAppContact.objects.get_or_create(phone=e164, defaults={"wa_id": digits, "language": user.preferred_language})`.
  - `notify_rider(delivery, rider, kind)`:
    1. `get_or_create` the `DeliveryNotification(delivery, rider, kind, attempt)` row; stop if it already existed.
    2. Write the `RiderInboxEntry`.
    3. `outbound.queue_template(contact, settings.WHATSAPP_TEMPLATE_…, params, Out.Trigger.ORDER_UPDATE)`.
    4. Link `outbound` and `flush(row.batch)`.
  - Register `notify_rider` into `services.NOTIFY_HOOKS` from `DeliveryConfig.ready()`.
  - Make T014 pass.
- [X] T020 [US1] Write the admin serializers in `backend/apps/delivery/serializers.py`:
  - `DeliveryListSerializer`: id, status, attempt, `attention`, nested `order` {number, region, street, contact_name, item_count, total, paid_at, status}, `rider` {id, name, phone, vehicle}, created_at, updated_at.
  - `DeliveryDetailSerializer`: adds `events` [{status, attempt, rider, actor_type, actor_name, note, created_at}], `notifications` [{kind, attempt, state, outbound_status, created_at}] and `failure_reason`.
  - `CandidateSerializer`: {id, name, phone, vehicle, regions, is_available, open_jobs, covers_region}.
  - Input serializers: `AssignSerializer`, `UnassignSerializer`, `StatusSerializer`.
- [X] T021 [US1] Implement `backend/apps/delivery/views.py` and `urls.py`. Everything is `IsShopAdmin` and documented with `extend_schema`.
  - `AdminDeliveryViewSet` (list/retrieve) at `admin/deliveries/`:
    - Filters: `status` (repeatable), `region`, `rider`, `attention`.
    - `attention` is annotated as failed OR (waiting and `created_at < now - DELIVERY_WAITING_ALERT_MINUTES`). Order by `-attention, created_at`. Paginated.
    - Actions `candidates`, `assign`, `unassign` and `status`, mapping `DeliveryError` codes to 400/409 bodies `{"detail","code"}`. `stale` includes `delivery`.
  - `create-from-order` view at `admin/orders/<number>/delivery/`.
  - Make T013 and T016 pass.
- [X] T022 [US1] Add the guard in `backend/apps/orders/views.py`: `AdminOrderViewSet`'s status action refuses `out_for_delivery`/`delivered` with 409 `use_deliveries` when `hasattr(order, "delivery")`. Use a `try` on `Delivery.DoesNotExist` via the related accessor, with no import of `apps.delivery` at module level. Make T015 pass, and check that the 001/002 order tests stay green.
- [ ] T023 [US1] Regenerate the web API types: `npm run gen:api` in `web/`, updating `web/src/lib/api/schema.d.ts`.
- [ ] T024 [P] [US1] Write `web/src/lib/queries/delivery.ts`. Use TanStack Query hooks through the bff, in the same style as `web/src/lib/queries/admin.ts`:
  - Queries: `useDeliveries(filters)`, `useDelivery(id)`, `useCandidates(id)`.
  - Mutations: `useAssign`, `useUnassign`, `useDeliveryStatus`, `useCreateDelivery(number)`.
  - Invalidate the list and the detail on success; surface `stale` by refetching.
- [ ] T025 [P] [US1] Add sw/en strings in `web/src/i18n/sw.ts` and `web/src/i18n/en.ts`:
  - `admin.deliveries.*`: list headings, the status labels for all 7 statuses, filters, attention badge, assign dialog, unassign, status override, create-delivery, the errors `stale`/`rider_unavailable`/`invalid_transition`/`use_deliveries`.
  - The nav labels.
- [ ] T026 [US1] Build `web/src/app/admin/deliveries/page.tsx`: a list with status, region and rider filters; failed and long-waiting rows highlighted; links to detail. Follow the `web/src/app/admin/orders/page.tsx` layout.
- [ ] T027 [US1] Build `web/src/app/admin/deliveries/[id]/page.tsx` plus client components (`delivery-detail.tsx`, `assign-dialog.tsx`):
  - Order summary and timeline of events.
  - The assign dialog lists candidates with region riders first, open jobs and availability; it disables unavailable riders and sends `expected_status`/`expected_rider`.
  - Unassign, and a status override with a required note for failed.
- [ ] T028 [US1] Add Deliveries to `web/src/app/admin/admin-nav.tsx`. In `web/src/app/admin/orders/[number]/order-detail.tsx`:
  - Link to the order's delivery when it exists, or show a "create delivery" button for paid/processing orders without one.
  - Show the `use_deliveries` error message.
- [ ] T029 [US1] Write `web/e2e/admin-deliveries.spec.ts` (Playwright, :3100 e2e stack): seed a paid order and a rider via `web/e2e/seed.py`, open `/admin/deliveries`, assign the rider, and see the status as assigned. Extend `seed.py` with a rider plus region if needed.

**Checkpoint**: US1 works end to end with seeded riders. `pytest apps/delivery apps/orders` is green, and so are web lint, typecheck and the e2e spec.

---

## Phase 4: User Story 2 – Rider handles the job on WhatsApp (P1) 🎯 MVP

**Goal**: an active rider's WhatsApp number is routed to the 003 agent with role `rider` and the four rider tools, each scoped to the rider's own jobs.

**Independent Test**: with a delivery assigned to a test rider, the fake model scripts `my_jobs`, `job_details` and `update_delivery(delivered)`. The replies are sent through `FakeGraph`, and the delivery and the order end as delivered.

### Tests for US2 (write first; they must fail)

- [ ] T030 [P] [US2] Write `backend/apps/delivery/tests/test_rider_tools.py`, calling the tools through `ai.tools.run_tool` with `ToolContext(role=RIDER, user=rider)`:
  - `my_jobs` returns only ACTIVE jobs of this rider, oldest first, at most 10.
  - `job_details` returns the contract fields, with `notes` inside the data wrapper.
  - `update_delivery` returns, according to the case:
    - picked_up / on_the_way / delivered: ok, with `recorded`
    - assigned→delivered: `recorded: [picked_up, delivered]`
    - a repeat: `already: true`, with no new event and no notification
    - a backwards move: `invalid_transition`, with `current`
    - failed without a reason: `reason_required`
    - failed with a reason: stores `failure_reason`
  - Another rider's order, a missing order and a closed job all give the same `not_found` (SC-005).
  - A job reassigned between lookup and lock gives `not_yours_anymore`.
  - `set_availability` toggles `is_available` and returns `active_jobs`.
  - The rider role never sees customer tools, and the customer roles never see rider tools.
- [ ] T031 [P] [US2] Write `backend/apps/delivery/tests/test_rider_routing.py`, driving the 004 pipeline with `whatsapp.processing.process` on inbound rows from a rider's number, with fake models:
  - An active rider gets `role="rider"` and the rider prompt, and the conversation's `user` is the rider.
  - A deactivated rider, or a rider whose profile is gone, is served as a customer.
  - STOP from an active rider answers `rider_stop` and leaves `updates_allowed` unchanged.
  - Staff takeover (`NEEDS_HUMAN`) records without answering.
  - A voice note from a rider is transcribed (`FakeSpeech`) and handled like text.
  - The 004 customer tests (`pytest apps/whatsapp`) stay green.

### Implementation for US2

- [ ] T032 [US2] Additive changes in `backend/apps/ai/tools.py`:
  - Add `RIDER = "rider"`, and keep `ALL_ROLES = (GUEST, CUSTOMER)`.
  - Make sure `tools_for(RIDER)` returns only the tools registered with `roles=(RIDER,)`, and `run_tool` refuses tools from another role.
- [ ] T033 [US2] Additive changes in `backend/apps/ai/prompts.py` and `backend/apps/ai/agent.py`:
  - Add a sw/en `RIDER_PROMPT` with the rules in `contracts/rider-tools.md`.
  - `system_prompt(language, no_think=False, history_notes="", role=None)` returns the rider prompt when `role == "rider"`.
  - `handle_message(..., *, role=None)` overrides the login-derived role when given, passes it to `ToolContext` and `system_prompt`, and records it in the message payload meta.
  - Customer behaviour is unchanged; `pytest apps/ai` must stay green.
- [ ] T034 [US2] Implement `backend/apps/delivery/rider_tools.py` and import it in `DeliveryConfig.ready()`. Register `my_jobs`, `job_details(order_number)`, `update_delivery(order_number, status enum, reason?)` (`mutates=True`) and `set_availability(available)` with `roles=(RIDER,)`.
  - Each tool normalizes the number to upper case and looks the job up with `Delivery.objects.filter(order__number=…, rider=ctx.user, status__in=ACTIVE)`.
  - Writes go through `services.change(..., actor=ctx.user, actor_type="rider", expect={"rider": ctx.user})`.
  - Results are wrapped with `prompts.wrap_data`.
  - Make T030 pass.
- [ ] T035 [US2] Additive changes in `backend/apps/whatsapp/processing.py`:
  - Add a `ROLE_RESOLVERS = []` extension list and a `rider: User | None = None` field on `Job`.
  - In `_process`, after `current_conversation`, set `job.rider` from the first resolver that returns a user.
  - `run_turn` and `record` pass `user=job.rider or contact.user` and `role="rider" if job.rider else None`.
  - When `job.rider` is set, skip `phone_orders` and `verified_phone`.
- [ ] T036 [US2] Register the delivery hooks from `DeliveryConfig.ready()` in `backend/apps/delivery/apps.py`:
  - Append `lambda job: riders.rider_for_contact(job.contact)` to `ROLE_RESOLVERS`.
  - Insert a `rider_stop_control(job)` handler (in `backend/apps/delivery/riders.py`) into `CONTROL_HANDLERS` before `updates_control`. It answers the STOP words from an active rider with `texts.rider_stop` through `processing.reply_fixed`/`send_system`.
  - Make T031 pass.
- [ ] T037 [US2] Add a "rider" badge field to the 003 admin conversation serializer in `backend/apps/ai/serializers.py` (`is_rider`, true when the conversation user has `role=rider`; additive). Show it in the existing admin conversations list on the web, if that list exists. Regenerate the types.

**Checkpoint (MVP)**: US1 + US2 green. Full backend suite green. Manual simulator flow from quickstart §2 steps 2–4.

---

## Phase 5: User Story 3 – Customer follows the delivery (P2)

**Goal**: the customer order and track pages show delivery progress. WhatsApp-placed orders get the "on the way" message with the rider's first name and phone, and one "couldn't deliver" message per failed attempt.

**Independent Test**: move a delivery through its statuses. Check `GET /api/orders/{number}/` → `delivery` (no rider phone, id, notes or reasons), and check the `FakeGraph` templates `order_on_the_way_rider` (once) and `order_delivery_failed` (once per attempt).

### Tests for US3 (write first)

- [ ] T038 [P] [US3] Write `backend/apps/delivery/tests/test_customer_view.py`:
  - The order detail (owner) and the track lookup include `delivery`: `{status, rider_first_name, rider_vehicle, events[{status, created_at}]}`. It is `null` without a delivery, and the rider fields are `null` while waiting.
  - No rider id, phone, last name, notes, failure_reason or attempt appears anywhere in the JSON.
  - Earlier-attempt events are kept.
- [ ] T039 [P] [US3] Extend `backend/apps/delivery/tests/test_notifications.py` with the customer part:
  - A WhatsApp-placed order reaching `out_for_delivery` with a rider sends `order_on_the_way_rider` [number, first name, rider phone] once. Without a rider it still sends the existing `order_out_for_delivery`.
  - Failed sends `order_delivery_failed` [number] once per attempt; a retry, then failing again, sends a second one.
  - `updates_allowed=False` gives `skipped`.
  - Web-placed orders get nothing.
  - A repeated "delivered" from the rider gives one `order_delivered` only.

### Implementation for US3

- [ ] T040 [US3] Additive change in `backend/apps/whatsapp/tasks.py`:
  - Add `ORDER_TEMPLATE_OVERRIDES = []`, each entry `callable(order, status) -> (template, values) | None`.
  - `notify_order_status` asks the overrides first and falls back to `_template_for` and the current values.
  - `pytest apps/whatsapp` stays green.
- [ ] T041 [US3] In `backend/apps/delivery/notifications.py`:
  - Add `on_the_way_override(order, status)`: for `out_for_delivery`, when `order.delivery.rider` is set, it returns `(settings.WHATSAPP_TEMPLATE_ORDER_ON_THE_WAY_RIDER, [number, first_name, phone])`.
  - Add `notify_customer_failed(delivery)`:
    - Only for orders with a `WhatsAppOrder` link.
    - Guarded by `DeliveryNotification(delivery, rider=None, kind="customer_failed", attempt)`.
    - Respects `updates_allowed` (state `skipped`).
    - Sends with the `ORDER_UPDATE` trigger.
  - Register both in `ready()`: the override into `ORDER_TEMPLATE_OVERRIDES`, and the failed sender into `NOTIFY_HOOKS`.
  - Make T039 pass.
- [ ] T042 [US3] Add the read-only `delivery` field to `OrderSerializer` in `backend/apps/orders/serializers.py`, through a `SerializerMethodField` that calls a function in `apps/delivery/serializers.py` (`customer_delivery_block(order)`), imported lazily. Prefetch `delivery__events` and `delivery__rider__rider_profile` in the order detail and track querysets. Make T038 pass, then regenerate `web/src/lib/api/schema.d.ts`.
- [ ] T043 [P] [US3] Write a vitest test, `web/src/components/shop/order-timeline.test.tsx`, for merging `delivery.events` into the order events by time:
  - "Rider assigned (Juma, Motorbike)" shows.
  - Failed shows "Couldn't deliver – we'll contact you".
  - No delivery means unchanged output.
- [ ] T044 [US3] Update `web/src/components/shop/order-timeline.tsx` (and `order-view.tsx` if it passes the props) to merge the delivery events. Add the `order.delivery.*` labels and `order.delivery.vehicles.*` in `web/src/i18n/{sw,en}.ts`. Make T043 pass.

**Checkpoint**: US3 green. Web test, lint and typecheck green.

---

## Phase 6: User Story 4 – Admin registers and manages riders (P2)

**Goal**: rider CRUD in the web admin with regions, a WhatsApp welcome carrying a 72 h single-use set-password link, deactivation blocked by open jobs, and the welcome status with resend.

**Independent Test**: `POST /api/auth/riders/` sends `rider_welcome` with a URL. `POST /api/auth/set-password/` with that uid/token returns 204, and a second time 400 `invalid_link`. Deactivating a rider with an active job gives 409 `open_jobs`. Once deactivated, the number routes as a customer.

### Tests for US4 (write first)

- [ ] T045 [P] [US4] Write `backend/apps/accounts/tests/test_riders.py`:
  - Create a rider with `regions` (required, at least 1), `preferred_language`, an E.164 phone (an invalid one gives 400). The user is `role=rider` with a profile, and one `rider_welcome` (`FakeGraph`) is sent with the first name plus a `{WEB_BASE_URL}/set-password?uid=…&token=…` URL, with `welcome_sent_at` set.
  - A phone that belongs to a customer gives 409 `phone_in_use` with `can_convert: true`. `convert_user: true` converts that customer. An admin's phone gives `can_convert: false`, and conversion is refused.
  - PATCH `is_active=false` with an active job gives 409 `open_jobs`. Without one it deactivates and sets `is_available=false`.
  - DELETE soft-deactivates under the same rules.
  - `resend-welcome` returns 202 and sends a new template (the attempt counter increments); it gives 409 `inactive` for a deactivated rider.
  - The `welcome` block shows `{sent_at, state, outbound_status}`, including a failed Graph send (US4-5).
  - List filters `active`, `available`, `region`.
  - `legacy_zone` is read-only.
  - Non-admins are refused.
- [ ] T046 [P] [US4] Write `backend/apps/accounts/tests/test_set_password.py`:
  - A valid uid/token gives 204, and the password is set.
  - Reusing the token gives 400 `invalid_link`.
  - An expired token gives `invalid_link`; patch the clock past `RIDER_SETUP_TOKEN_HOURS`.
  - A bad uid, a non-rider and an inactive rider all give the same `invalid_link`.
  - A weak password gives `{"password": [...]}`.
  - The throttle scope is `set_password`.

### Implementation for US4

- [ ] T047 [P] [US4] Write `backend/apps/accounts/tokens.py`: `RiderSetupTokenGenerator(PasswordResetTokenGenerator)`, with the timeout set from `settings.RIDER_SETUP_TOKEN_HOURS * 3600`, plus a `rider_setup_url(user)` helper that builds `{WEB_BASE_URL}/set-password?uid=<urlsafe_b64>&token=…`.
- [ ] T048 [US4] Extend `RiderSerializer` in `backend/apps/accounts/serializers.py`:
  - Writable: `regions` (slug by region name, min 1), `preferred_language` (sw|en), `is_active`, `convert_user` (write-only).
  - Read-only: `open_jobs`, `welcome`, `legacy_zone`.
  - `zone` is no longer writable, `password` is optional, and the phone is validated with `normalize_phone` against E.164.
  - Raise the `phone_in_use` conflict with `can_convert`.
- [ ] T049 [US4] Extend `RiderViewSet` in `backend/apps/accounts/views.py`:
  - Filters `active`, `available`, `region`.
  - `perform_create` queues the welcome on commit.
  - PATCH/DELETE run the deactivation guard (409 `open_jobs`, using `apps.delivery.riders.open_jobs` imported lazily) and soft-delete.
  - A `resend-welcome` action (202 / 409 `inactive`).
  - Add a `SetPasswordView` (AllowAny, `ScopedRateThrottle` scope `set_password`) at `auth/set-password/` in `backend/apps/accounts/urls.py`.
- [ ] T050 [US4] In `backend/apps/delivery/notifications.py`, add `send_welcome(rider)`:
  - `DeliveryNotification(delivery=None, rider, kind="rider_welcome", attempt=n)`, where n = the previous welcome count + 1.
  - The template [first name, setup URL]; set `welcome_sent_at`.
  - A `welcome_status(rider)` helper for the serializer.
  - Make T045–T046 pass.
- [ ] T051 [US4] Regenerate the web types. Add `useRiders`, `useRider`, `useSaveRider`, `useResendWelcome` and `useDeliveryRegions` (reusing the existing one if present) to `web/src/lib/queries/delivery.ts`. Add `admin.riders.*` strings in `web/src/i18n/{sw,en}.ts`.
- [ ] T052 [US4] Build `web/src/app/admin/riders/page.tsx` (a list with the active/available/region filters and open jobs), `riders/new/page.tsx` and `riders/[id]/page.tsx`, sharing a `rider-form.tsx`:
  - Fields: name, phone, vehicle, regions multi-select, language, available.
  - Deactivate, with the `open_jobs` error.
  - Welcome status with a resend button.
  - The `phone_in_use` → convert prompt.
  - Add Riders to `admin-nav.tsx`.
- [ ] T053 [P] [US4] Build the public page `web/src/app/(shop)/set-password/page.tsx` plus `set-password-form.tsx`: password and confirm fields; on success, "Password set. You'll use it in the rider app."; the `invalid_link` message. Add `setPassword.*` sw/en strings. Write a vitest test, `set-password-form.test.tsx` (mismatch, success and invalid_link states).

**Checkpoint**: US4 green. A deactivated rider's number routes as a customer (covered by T031).

---

## Phase 7: User Story 5 – Failed deliveries and auto-assignment (P3)

**Goal**: the admin retries failed deliveries (attempt+1, history kept). An optional auto-assign gives new deliveries to the least-loaded available rider in the region.

**Independent Test**: fail and retry a delivery (attempt 2, earlier events kept). With auto-assign on and two Kinondoni riders (one with an active job), paying a new order assigns the idle one.

### Tests for US5 (write first)

- [ ] T054 [P] [US5] Write `backend/apps/delivery/tests/test_auto_assign.py`:
  - Off (the default) assigns nothing.
  - On picks the rider with fewer ACTIVE jobs; on a tie, the one with the oldest `last_assigned_at` (nulls first), then the lowest id.
  - Riders that are unavailable, inactive or outside the region are never chosen.
  - With no candidate, the delivery stays waiting and shows `attention` after `DELIVERY_WAITING_ALERT_MINUTES`.
  - The auto-assigned rider gets `delivery_assigned`, and the event's actor_type is `system`.
- [ ] T055 [P] [US5] Extend `backend/apps/delivery/tests/test_admin_api.py`:
  - `retry` with `rider=null` gives waiting with attempt 2; with a rider, assigned with attempt 2. The earlier events stay.
  - Retry from a non-failed status gives 409 `invalid_transition`.
  - `GET/PATCH /api/admin/delivery-settings/` is admin-only and records `updated_by`.

### Implementation for US5

- [ ] T056 [US5] In `backend/apps/delivery/services.py`:
  - `choose_rider(order)`: assignable riders with `rider_profile__regions__name=order.region`, annotated with the open-job count, ordered by `open_jobs, F("rider_profile__last_assigned_at").asc(nulls_first=True), id`.
  - `auto_assign(delivery)`: a no-op unless `DeliverySettings.get().auto_assign`.
  - Wire `auto_assign` into the `paid` path in `signals.py`.
  - Make T054 pass.
- [ ] T057 [US5] Add a `retry` action and an `AdminDeliverySettingsView` (GET/PATCH) at `admin/delivery-settings/` to `backend/apps/delivery/views.py`, `serializers.py` and `urls.py`. Make T055 pass, then regenerate the web types.
- [ ] T058 [US5] On the web:
  - Add `useRetry`, `useDeliverySettings` and `useSaveDeliverySettings` in `web/src/lib/queries/delivery.ts`.
  - Add a retry button (with an optional rider) on `web/src/app/admin/deliveries/[id]/` for failed deliveries.
  - Add an auto-assign switch on `web/src/app/admin/deliveries/page.tsx`.
  - Add the sw/en strings.

**Checkpoint**: every story is green.

---

## Phase 8: Rider inbox API (FR-020) and the rider evaluation (SC-004)

These are cross-story, API only.

- [ ] T059 [P] Write `backend/apps/delivery/tests/test_inbox.py`:
  - `GET /api/rider/inbox/?unread=1` returns only the rider's own entries, with `title` in the rider's language and an `unread` count.
  - `POST /api/rider/inbox/{id}/read/` gives 204 and is idempotent; another rider's entry gives 404.
  - Non-riders get 403.
- [ ] T060 Implement `RiderInboxViewSet` (`IsRider`) in `backend/apps/delivery/views.py` and `urls.py` at `rider/inbox/`. Make T059 pass.
- [ ] T061 [P] Write `backend/apps/delivery/eval/rider_cases.json`: 30 or more cases, sw and en, text (plus voice clip paths when present). Each case has `{text, setup: {jobs: [...]}, expect: {tool, arguments}}` and covers my_jobs, job_details, every update_delivery status, failed with a reason, availability, an off-topic question, and someone else's order.
- [ ] T062 Implement the management command `backend/apps/delivery/management/commands/delivery_rider_eval.py`:
  - Options `--database`, `--report`, `--limit`.
  - It seeds a rider and its jobs per case on the given DB, runs each case through `whatsapp_simulate --inline` (`apps/whatsapp/management/commands/whatsapp_simulate.py`) from the rider's number, and compares the first rider tool call with `expect`.
  - It prints the accuracy (target ≥ 90%).
  - Add a test with fake models in `backend/apps/delivery/tests/test_commands.py`.

---

## Phase 9: Polish and cross-cutting

- [ ] T063 [P] Add a sandbox test (`@pytest.mark.sandbox`) to `backend/apps/delivery/tests/test_sandbox.py` that sends `delivery_assigned` to the Meta test number when the env credentials are set.
- [ ] T064 Run the full backend suite and fix regressions:
  - Check that the 001–004 test counts are unchanged.
  - Run `manage.py makemigrations --check` and `manage.py spectacular --validate`.
- [ ] T065 Run the web checks and fix them: `npm run test && npm run lint && npm run typecheck` and `npx playwright test e2e/admin-deliveries.spec.ts`.
- [ ] T066 Run the manual simulator flow from `specs/005-delivery-riders/quickstart.md` §2 on `shop_sim`, then tick the results into quickstart.md (or note the deviations).
- [ ] T067 [P] Update `README.md` and the docs where 004 documented WhatsApp setup: list the 6 new templates and `WEB_BASE_URL`.

---

## Dependencies and execution order

- **Setup (Ph 1)**: no dependencies. **Foundational (Ph 2)** depends on Setup and blocks every story.
- **US1 (Ph 3)** runs after Ph 2. **US2 (Ph 4)** runs after Ph 2. Its tests seed assigned deliveries directly through `services.assign`, so it doesn't need the US1 web or API; in practice, it comes after US1's backend (T017–T022).
- **US3, US4 and US5** each need only Ph 2 (`change()` and its `NOTIFY_HOOKS`), so they can run in parallel after the MVP:
  - US3 touches `whatsapp/tasks.py`, `orders/serializers.py` and the shop timeline.
  - US4 touches `accounts/*` and the riders web pages.
  - US5 touches `delivery/services.py`, `views.py` and the deliveries web pages. That overlaps with US1's files, so do it after US1.
- **Ph 8** follows US1 (the inbox rows come from US1 notifications) and US2 (the eval uses the rider routing).
- **Polish** comes last.

Within a story: tests → models → services → API → web.

## Parallel examples

- **Ph 2**: T006 (accounts model) ∥ T007 (admin) ∥ T011 (riders.py), after T004–T005.
- **US1 tests**: T012 ∥ T013 ∥ T014 ∥ T015 ∥ T016. Web: T024 ∥ T025 after T023.
- **US2 tests**: T030 ∥ T031.
- **After the MVP**: US3 (T038–T044) ∥ US4 (T045–T053).

## Implementation strategy

1. **MVP**: Ph 1 → Ph 2 → US1 → US2. Stop and validate with quickstart §2 steps 2–4, with seeded riders.
2. **Then**: US3 (customer visibility) → US4 (rider admin and welcome) → US5 (retry and auto-assign) → Ph 8 → Polish.
3. Commit after each phase. Keep the 001–004 suites green at every checkpoint.
