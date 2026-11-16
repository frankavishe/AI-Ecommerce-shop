# Contract: Delivery notifications (WhatsApp templates and the rider inbox)

All sends go through `whatsapp.outbound.queue_template` plus `flush`, so the 004 retries, error classes and outbound status tracking apply. Template names come from settings (`.env`) and need Meta approval in sw and en before going live (R7).

## Rider templates

These ignore `updates_allowed` (FR-019). The rider's language is `User.preferred_language`.

| Kind | Setting (default) | Body parameters | When |
|---|---|---|---|
| `rider_welcome` | `WHATSAPP_TEMPLATE_RIDER_WELCOME` (`rider_welcome`) | 1 first name, 2 set-password URL | Rider created, or resend-welcome |
| `rider_assigned` | `WHATSAPP_TEMPLATE_DELIVERY_ASSIGNED` (`delivery_assigned`) | 1 order no., 2 region, 3 street, 4 contact name, 5 item count | Delivery assigned to this rider (including a reassign or retry) |
| `rider_removed` | `WHATSAPP_TEMPLATE_DELIVERY_REMOVED` (`delivery_removed`) | 1 order no. | Unassigned, or reassigned away from this rider |
| `rider_cancelled` | `WHATSAPP_TEMPLATE_DELIVERY_CANCELLED` (`delivery_cancelled`) | 1 order no. | The order is cancelled while assigned to this rider |

Suggested Swahili bodies (for Meta submission):
- **delivery_assigned**: "Kazi mpya: oda {{1}}, {{2}} – {{3}}. Mteja: {{4}}, bidhaa {{5}}. Jibu hapa kwa maelezo zaidi."
- **delivery_removed**: "Oda {{1}} imeondolewa kwenye kazi zako."
- **delivery_cancelled**: "Oda {{1}} imesitishwa. Usiipeleke."
- **rider_welcome**: "Karibu {{1}}! Utapokea kazi za usafirishaji hapa. Weka nenosiri: {{2}}"

## Customer templates

These only go to orders placed on WhatsApp (a `WhatsAppOrder` link) and respect `updates_allowed` (004 R14).

| Event | Setting (default) | Parameters | Once-guard |
|---|---|---|---|
| Order → `out_for_delivery`, delivery has a rider | `WHATSAPP_TEMPLATE_ORDER_ON_THE_WAY_RIDER` (`order_on_the_way_rider`) | 1 order no., 2 rider first name, 3 rider phone | The existing `WhatsAppOrderNotification(order, status)` |
| Order → `out_for_delivery`, no rider (admin action before 005) | Existing `order_out_for_delivery` | 1 order no. | Same |
| Delivery → `failed` | `WHATSAPP_TEMPLATE_DELIVERY_FAILED` (`order_delivery_failed`) | 1 order no. | `DeliveryNotification(delivery, kind=customer_failed, attempt)` |

Suggested Swahili body for **order_delivery_failed**: "Samahani, hatukuweza kufikisha oda {{1}} leo. Tutawasiliana nawe kupanga muda mwingine."

The failure reason is never included (FR-021a).

## The `out_for_delivery` hook

Two hooks are added in `whatsapp/tasks.py`:
- `ORDER_TEMPLATE_OVERRIDES: list[callable(order, status) -> (template, values) | None]`
- `notify_order_status` asks the overrides first, then falls back to `_template_for`.

The delivery app registers the rider override in `DeliveryConfig.ready()`.

## Rider inbox API (`IsRider`)

- `GET /api/rider/inbox/?unread=1`
  - Returns `{"results": [{"id", "kind", "order_number", "title", "read_at", "created_at"}], "unread": 2}`.
  - `title` is in the rider's language.
- `POST /api/rider/inbox/{id}/read/` → 204. It's idempotent. Another rider's entry gives 404.

## Idempotency rules (Constitution IV)

- One `DeliveryNotification` row per `(delivery, rider, kind, attempt)`. The row is created inside the same transaction as the event, and the send is queued `on_commit`. A replay finds the row and stops.
- A send failure only marks the row and the outbound record. It never rolls back the delivery change.
