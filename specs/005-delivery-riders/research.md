# Research: Delivery and Riders (005)

Decisions taken while planning. Each has a decision, the reasons, and the alternatives that were rejected. The R numbers are referenced from plan.md, data-model.md and the contracts.

## R1. Where the code lives

- **Decision**: a new app, `backend/apps/delivery`, holds the delivery models, services, the rider tools, the admin and rider APIs, notifications and tasks. Changes elsewhere are additive hooks:
  - `accounts`: the rider profile gets more fields, a set-password endpoint and a welcome action.
  - `ai`: a `rider` role, plus a `role=` keyword on `handle_message`.
  - `whatsapp`: one routing hook, one STOP hook and one template hook.
  - `orders`: a `delivery` block in the order serializer, and a guard on admin order transitions.
- **Rationale**: this follows the 004 pattern (one app per channel or domain), so 001–004 code stays readable and their tests stay green.
- **Alternatives**: putting delivery into `orders`. Rejected: it mixes rider and WhatsApp concerns into the commerce core and makes `orders` import `whatsapp`.

## R2. One delivery row per order, with attempts

- **Decision**: `Delivery` has a `OneToOneField(Order)` and an `attempt` counter, which starts at 1. A retry after a failure reuses the row: it increments `attempt`, clears the rider and failure reason, and goes to `waiting` or `assigned`. All history lives in `DeliveryEvent`, and each event stores its attempt number.
- **Rationale**: the one-to-one constraint makes FR-001 ("exactly one", even with webhook replays) a database guarantee, and lets the order page join the delivery cheaply. There's never more than one open delivery per order anyway.
- **Alternatives**: one row per attempt with a partial unique index on open rows. Rejected: more joins and more states, for a history that `DeliveryEvent` already keeps.

## R3. Creating the delivery when an order is paid (FR-001)

- **Decision**: a `post_save` receiver on `orders.OrderEvent` (created, not raw) with status `paid` runs `Delivery.objects.get_or_create(order=…)` on commit. It then runs auto-assign when that's switched on (R8). The same receiver handles `cancelled`: it cancels an open delivery and tells the assigned rider (FR-004).
  - `orders.transition()` is the one place each status change goes through, and payment replays don't create a second `paid` event (004 R14).
  - The admin can create a delivery by hand (FR-005) for orders that were already `paid` or `processing` before this feature, using the same `get_or_create`.
- **Rationale**: this mirrors the 004 notification receiver, so the payments code needs no change.
- **Alternatives**: calling into delivery from `payments.services`. Rejected: it couples payments to delivery and misses admin-driven `needs_review → paid`.

## R4. Keeping order and delivery statuses consistent (FR-002, FR-004)

- **Decision**: one service function, `delivery.services.change(delivery, to, actor, *, rider=None, note="", expect=None)`. It runs in `transaction.atomic()` with `select_for_update()` on the delivery row, then:
  1. Checks the move against the delivery transition table (data-model.md).
  2. If `expect` is given (the rider or status the caller last saw), refuses with `StaleDelivery` when the row has changed since (FR-009, R9).
  3. Writes the `DeliveryEvent`.
  4. Moves the order forward through `orders.services.transition()` only where the mapping requires it and the order isn't there already:
     - assigned → order `processing` (if it's still `paid`)
     - picked up or on the way → `out_for_delivery`
     - delivered → `delivered`
  5. Queues notifications on commit (R6, R7).

  A failed delivery leaves the order at `out_for_delivery`. A retry leaves the order where it is.
- **Admin order page guard**: once an order has a delivery, the existing admin order-status action refuses `out_for_delivery` and `delivered` with "Use Deliveries" (409, `code="use_deliveries"`). `processing` and `cancelled` stay allowed. This is the only behaviour change in 001/002 code, and it's additive (a check before `transition()`).
- **No loops**: the delivery receiver only reacts to order `paid` and `cancelled`, which delivery never produces.
- **Rationale**: the order statuses customers already see stay the single public status, and existing notifications still fire exactly once because they hang off `OrderEvent`.
- **Alternatives**: deriving the order status from the delivery on read. Rejected: it breaks 001–004 queries, filters and notifications.

## R5. Rider tools in the 003 agent (FR-014–FR-018, FR-026)

- **Decision**:
  - `ai.tools` gets a third role constant, `RIDER = "rider"`. `ALL_ROLES` stays `(GUEST, CUSTOMER)`, so riders never get customer tools.
  - `handle_message(..., role=None)` is a new keyword-only argument. When it's given, it overrides the role derived from login.
  - `prompts.system_prompt(..., role=GUEST)` picks a short rider prompt in sw/en: "you help delivery riders with their jobs only; never invent order data; tools are the only source".
  - `apps/delivery/rider_tools.py` registers the rider tools with `ai.tools.register(..., roles=(RIDER,))` and is imported in `DeliveryConfig.ready()`:
    - `my_jobs()`
    - `job_details(order_number)`
    - `update_delivery(order_number, status, reason?)`, with `status ∈ {picked_up, on_the_way, delivered, failed}`
    - `set_availability(available)`
  - Every tool resolves the delivery with `Delivery.objects.filter(order__number=…, rider=ctx.user, status__in=OPEN)`. If that finds nothing, it returns the same `not_found` message as for a missing order (FR-016).
  - `update_delivery` "delivered" on an `assigned` job writes `picked_up` and then `delivered` (US2-7).
  - Repeating the current status returns `already` and has no side effects (FR-017).
  - Tool results are serialized into the existing data wrapper, so order notes and addresses stay data (FR-026).
- **Rationale**: this reuses the loop, the fallbacks and the timeouts of 003, plus the 004 voice and photo handling. The role filter in `run_tool` already refuses a tool from another role.
- **Alternatives**: a separate rider agent loop, rejected because the two loops would drift. Keyword commands without the model ("JOBS", "DONE 1042"), rejected because the spec asks for natural Swahili and voice. Fixed reply buttons are a possible later fallback, noted for tasks as optional.

## R6. Routing a rider's WhatsApp number (FR-014, edge cases)

- **Decision**:
  - `whatsapp.processing` gets a new extension list, `ROLE_RESOLVERS`, which the delivery app fills: `lambda job: delivery.riders.rider_for_contact(job.contact)`.
  - An active rider is a `User` with `role=rider`, `is_active=True` and `phone == contact.phone`, with a rider profile.
  - When a resolver returns a rider, `job.rider` is set. `run_turn` and `record` then pass `user=rider, role="rider"`, and the conversation's `user` is the rider. A rider number reuses the same contact and conversation rows.
  - A deactivated rider gets no match and is served as a customer.
- **STOP from a rider**: a new control handler, registered before `updates_control`, answers STOP from an active rider with the fixed `rider_stop` text. It doesn't change `updates_allowed`.
- **Other 004 behaviour**: staff takeover, rate limits, the 7-day reset and voice transcription apply unchanged. The 004 checkout buttons and payment extras never trigger, because rider tools never set `checkout_summary`.
- **Rationale**: the phone is the identity WhatsApp vouches for, and riders are created with their phone by the admin, so no linking step is needed.

## R7. WhatsApp messages: riders and customers (FR-019, FR-021, FR-021a)

- **Rider messages**: `delivery.notifications` gets or creates a `WhatsAppContact` for the rider's phone (`wa_id` = E.164 digits without `+`, language = the rider's `preferred_language`). It queues approved templates with `whatsapp.outbound.queue_template` and `flush`:

  | Event | Template setting | Default name | Parameters |
  |---|---|---|---|
  | Rider created | `WHATSAPP_TEMPLATE_RIDER_WELCOME` | `rider_welcome` | first name, set-password URL |
  | Job assigned | `WHATSAPP_TEMPLATE_DELIVERY_ASSIGNED` | `delivery_assigned` | order no., region, street, contact name, item count |
  | Job removed | `WHATSAPP_TEMPLATE_DELIVERY_REMOVED` | `delivery_removed` | order no. |
  | Job cancelled | `WHATSAPP_TEMPLATE_DELIVERY_CANCELLED` | `delivery_cancelled` | order no. |

  The amount already paid is not sent: there's no cash on delivery, so it doesn't matter to the rider. Templates are used even inside the 24-hour window, which keeps one code path and is always allowed. Rider messages ignore `updates_allowed` (FR-019).
- **Customer messages**: these stay limited to orders placed on WhatsApp (004 R14: a `WhatsAppOrder` link plus `updates_allowed`).
  - **On the way with a rider**: a new hook list, `ORDER_TEMPLATE_OVERRIDES`, in `whatsapp.tasks._template_for`/values. The delivery app registers an override for `out_for_delivery`: when the order's delivery has a rider, it uses `WHATSAPP_TEMPLATE_ORDER_ON_THE_WAY_RIDER` (`order_on_the_way_rider`: order no., rider first name, rider phone). The existing `(order, status)` unique row keeps it to once.
  - **Failed attempt (FR-021a)**: the delivery app sends `WHATSAPP_TEMPLATE_DELIVERY_FAILED` (`order_delivery_failed`: order no.). It's guarded by a unique `DeliveryNotification(delivery, kind="customer_failed", attempt)`, so it goes out once per attempt.
- **Delivery notifications table**: `DeliveryNotification(delivery, kind, attempt, rider)` is unique together, and links to the `WhatsAppOutboundMessage`. It makes rider and failure messages idempotent, and lets the admin see whether the welcome or job message was delivered (US4-5).
- **Alternatives**: free-form text inside the window and templates outside it. Rejected: two paths, and riders often message late at night.
- **Open item**: the six new templates need Meta approval (sw + en). Tests use `FakeGraph`.

## R8. Auto-assign (FR-008)

- **Decision**: `DeliverySettings` is a singleton row (pk=1) with `auto_assign` (default false). When a delivery is created with auto-assign on, `choose_rider(order)` picks a rider:
  1. Candidates are active riders with `is_available` who cover `DeliveryRegion(name=order.region)`.
  2. Order them by open-job count, then `last_assigned_at` (nulls first), then id.
  3. Take the first and call `change(… assigned, actor=system)`.

  With no candidate, the delivery stays `waiting`, and the admin list flags it as `waiting > 15 min` (the threshold is configurable, `DELIVERY_WAITING_ALERT_MINUTES=15`).
- **Rationale**: this is a deterministic rule and easy to test. Region names are already unique.

## R9. Concurrency (FR-009, edge cases)

- **Decision**: every write goes through `change()` with `select_for_update()` on the delivery row.
  - Admin actions send `expected_status` (and `expected_rider` for reassign). A mismatch gives 409 `stale` with the current delivery in the body.
  - Rider tools check `rider == ctx.user` after taking the lock. If the job was moved, the rider is told it's no longer theirs.
- **Rationale**: this matches the row-lock style used for stock (Constitution II).

## R10. Riders: regions, deactivation, set-password link (FR-010–FR-013)

- **Profile changes**: `RiderProfile` gets:
  - `regions` (M2M `orders.DeliveryRegion`)
  - `last_assigned_at`
  - `welcome_sent_at`

  The data migration matches the existing free-text `zone` to a region by case-insensitive name. The field is then kept read-only, as `legacy_zone`, until a later cleanup. Preferred language uses the existing `User.preferred_language`, and the active flag uses `User.is_active`.
- **Deactivation**: `PATCH is_active=false` is refused with 409 `open_jobs` while the rider has any delivery in `assigned`, `picked_up` or `on_the_way`.
- **Creating a rider from an existing user**: when the phone belongs to an existing customer (not an admin), the API returns 409 `phone_in_use` with `can_convert=true`. Posting `convert_user=true` turns that user into a rider. Admins can't be converted.
- **Set-password link**: `apps/accounts/tokens.py` holds `RiderSetupTokenGenerator(PasswordResetTokenGenerator)` with a 72-hour timeout (`RIDER_SETUP_TOKEN_HOURS=72`). It's single-use for free, because the token hash includes the password, so it's invalid once the password is set.
  - The URL is `{WEB_BASE_URL}/set-password?uid=…&token=…`.
  - `POST /api/auth/set-password/` takes `uid`, `token` and `password`, and runs Django's password validators.
  - The resend action issues a fresh token. Old tokens die when the password changes; an unused older token stays valid until it expires, which is acceptable because it's tied to the same phone.
  - The web gets one small public page, `/set-password` (a password form). It's an account page, not a rider screen; riders don't log in anywhere else yet (clarification Q4).
- **Availability on WhatsApp**: the `set_availability` tool (FR-013).

## R11. Rider inbox (FR-020)

- **Decision**: `RiderInboxEntry(rider, kind, delivery, title_sw, title_en, read_at)` is written in the same transaction as the event. The API has two endpoints, `GET /api/rider/inbox/` and `POST …/{id}/read/`, both `IsRider`. There's no web UI; the Phase 7 app will use them.

## R12. Customer view (FR-022)

- **Decision**: `OrderSerializer` (customer order page and track page) gets a read-only `delivery` field:
  - `status`, `rider_first_name`, `rider_vehicle`
  - `events`: status and time only, with no rider ids, notes or failure reasons
  - `null` when there's no delivery

  The web `OrderTimeline` merges the delivery events into the order timeline, with new sw/en labels: "Rider assigned", "Picked up", "On the way", "Delivered", "Couldn't deliver".
- **Rationale**: this is additive. 002 clients ignore the new field until they're updated, and failure reasons can contain rider remarks the customer shouldn't see.

## R13. Admin web (FR-023, FR-024)

- **Decision**: new pages under `web/src/app/admin`, in the same style as the orders and products pages (server components plus bff queries):
  - `deliveries/`: list filterable by status, region and rider, with failed and long-waiting rows highlighted
  - `deliveries/[id]`: timeline, plus assign, reassign, unassign, retry, cancel and create-from-order actions
  - `riders/` and `riders/[id]`: form, availability, deactivate, resend welcome, welcome delivery status
  - an auto-assign switch on the deliveries list

  The admin order detail page links to its delivery.

## R14. Evaluating the rider assistant (SC-004)

- **Decision**: a management command, `delivery_rider_eval`, runs ≥30 scripted rider turns from `apps/delivery/eval/rider_cases.json` (sw and en; text, plus voice clips when present) against a seeded scratch DB. It reports how many led to the correct tool and arguments. It reuses the `whatsapp_simulate --inline` machinery. It's run on the GPU model before sign-off, and CPU runs are informational only (003/004 experience).

## R15. Testing (Constitution VI)

- **Approach**: tests are written first for each story.
  - Graph, the models and speech are faked (`FakeGraph`, the 003 fake models scripted to emit the rider tool calls, `FakeSpeech`).
  - Failure cases are covered: replayed `paid`, a stale assign, a wrong rider asking for an order, a backwards status, a deactivated rider's number, STOP from a rider, the welcome failing, a token that's expired or used, deactivation with open jobs, double "delivered" giving one notification, and a failed attempt sending one message per attempt.
  - Web: vitest for the timeline merge, and one Playwright spec for admin assign.
  - Real Meta sends stay under the `sandbox` marker.
