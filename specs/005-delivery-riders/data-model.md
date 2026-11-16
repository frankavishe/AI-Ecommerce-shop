# Data Model: Delivery and Riders (005)

The new tables are in `apps/delivery`. Changes to existing tables are marked **(changed)**. Research references: R2–R11.

## Delivery

One per order (R2).

| Field | Type | Notes |
|---|---|---|
| id | bigint PK | |
| order | OneToOne → `orders.Order` (PROTECT), `related_name="delivery"` | Makes "exactly one delivery per order" (FR-001) a database rule |
| status | char(12) | `waiting` · `assigned` · `picked_up` · `on_the_way` · `delivered` · `failed` · `cancelled` |
| rider | FK → `accounts.User`, null, SET_NULL, `related_name="deliveries"` | Must have `role=rider`. Set in `assigned`, `picked_up`, `on_the_way` and the closed statuses. Null in `waiting` and `cancelled` (when it was never assigned) |
| attempt | positive smallint, default 1 | Increased on retry after `failed` |
| failure_reason | char(255), blank | The rider's words. Set only in `failed`. Never shown to customers |
| assigned_at, picked_up_at, delivered_at, failed_at | datetime, null | Set for the current attempt |
| created_at, updated_at | datetime | |

Indexes: `(status, created_at)` and `(rider, status)`.
Check constraint: `rider IS NOT NULL` when status ∈ {assigned, picked_up, on_the_way}.

Open statuses: `waiting`, `assigned`, `picked_up`, `on_the_way`. Active rider jobs, which block deactivation and count toward load: `assigned`, `picked_up`, `on_the_way`.

### Delivery transitions (FR-002)

| From | To | Who | Order side effect (R4) |
|---|---|---|---|
| waiting | assigned | admin, system (auto-assign) | `paid → processing` |
| assigned | assigned (another rider) | admin | — |
| assigned | waiting (unassign) | admin | — |
| assigned | picked_up | rider, admin | `processing → out_for_delivery` |
| assigned | delivered | rider (records `picked_up` then `delivered`, US2-7) | → `out_for_delivery` → `delivered` |
| picked_up | on_the_way | rider, admin | (already `out_for_delivery`) |
| picked_up, on_the_way | delivered | rider, admin | `out_for_delivery → delivered` |
| picked_up, on_the_way | failed (reason required) | rider, admin | none (the order stays `out_for_delivery`) |
| failed | waiting or assigned (retry, `attempt+1`) | admin | none |
| any open status, failed | cancelled | system (order cancelled), admin (via order cancel) | — (the order cancel comes first) |

`delivered` and `cancelled` are final. Repeating the current status is a no-op that returns `already` (FR-017). Moving backwards is refused with `invalid_transition`.

## DeliveryEvent

| Field | Type | Notes |
|---|---|---|
| id | bigint PK | |
| delivery | FK → Delivery, CASCADE, `related_name="events"` | |
| status | char(12) | The status entered. `assigned` is used for reassignments too |
| attempt | smallint | Copied from the delivery |
| rider | FK → User, null | The rider after this event |
| actor_type | char(8) | `admin` · `rider` · `system` |
| actor | FK → User, null | |
| note | char(255), blank | Required for `failed`. "unassigned from X" for removals |
| created_at | datetime | |

Ordering: `created_at`, `id`.

## DeliveryNotification

Makes sends idempotent and records their outcome (R7).

| Field | Type | Notes |
|---|---|---|
| id | bigint PK | |
| delivery | FK → Delivery, null | Null for `rider_welcome` |
| rider | FK → User, null | The recipient when it's a rider |
| kind | char(20) | `rider_welcome` · `rider_assigned` · `rider_removed` · `rider_cancelled` · `customer_failed` |
| attempt | smallint, default 1 | The welcome uses a resend counter here |
| outbound | FK → `whatsapp.WhatsAppOutboundMessage`, null | Gives the delivery status of the send |
| state | char(8) | `queued` · `skipped` · `failed` |
| created_at | datetime | |

Unique together: `(delivery, rider, kind, attempt)`. A partial unique on `(rider, kind, attempt)` covers the welcome, where `delivery` is null.

## RiderInboxEntry

FR-020; API only.

| Field | Type | Notes |
|---|---|---|
| id | bigint PK | |
| rider | FK → User, CASCADE, `related_name="inbox"` | |
| kind | char(12) | `assigned` · `removed` · `cancelled` |
| delivery | FK → Delivery, CASCADE | |
| title_sw, title_en | char(160) | Rendered from fixed texts with the order number |
| read_at | datetime, null | |
| created_at | datetime | |

## DeliverySettings

A singleton with pk=1, created by the migration.

| Field | Type | Notes |
|---|---|---|
| auto_assign | bool, default False | FR-008 |
| updated_at, updated_by | datetime, FK → User null | |

## accounts.RiderProfile **(changed)**

| Field | Change |
|---|---|
| regions | **new** M2M → `orders.DeliveryRegion`, `related_name="riders"`. At least one is required on create (FR-010) |
| last_assigned_at | **new** datetime, null. The auto-assign tie-break (R8) |
| welcome_sent_at | **new** datetime, null |
| zone | kept as is (read-only in the API, shown as `legacy_zone`). A data migration copies a matching region name into `regions` |

The rider's identity, language and active flag stay on `User`: `first_name`, `last_name`, `phone` (unique, E.164), `preferred_language`, `is_active`, and `role=rider`.

**Active rider** (R6): `role=rider`, `is_active=True`, and a profile exists. **Assignable**: an active rider whose profile has `is_available=True`.

## orders **(changed, read-only additions)**

- `OrderSerializer.delivery` is a new read-only nested field (R12): `{status, rider_first_name, rider_vehicle, events: [{status, created_at}]}` or `null`.
- Admin order status action: refuses `out_for_delivery` and `delivered` with 409 `use_deliveries` when `order.delivery` exists (R4).

No schema changes to `orders`.

## ai **(changed, no schema change)**

- `tools.RIDER = "rider"`. Rider tools are registered with `roles=(RIDER,)`.
- `agent.handle_message(..., role=None)` takes a new keyword argument. `prompts.system_prompt(..., role=GUEST)` picks the rider prompt for `role="rider"`.

## whatsapp **(changed, no schema change)**

- `processing.ROLE_RESOLVERS` is a new extension list. `Job.rider` is set when a resolver matches.
- A rider STOP handler is registered ahead of `updates_control`.
- `tasks.ORDER_TEMPLATE_OVERRIDES` is a new extension list used by `notify_order_status` to choose the template and its values.
