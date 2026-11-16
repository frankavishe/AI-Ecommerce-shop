# Contract: Admin delivery and rider API

All endpoints require `IsShopAdmin` (FR-025). They're documented in drf-spectacular, and the web types are regenerated (`npm run gen:api`). Errors use the existing shape, `{"detail": "...", "code": "..."}`.

## Deliveries — `/api/admin/deliveries/`

### `GET /` — list

- **Query parameters**:
  - `status` (repeatable)
  - `region`
  - `rider` (user id)
  - `attention=1`: only failed deliveries, and waiting ones older than `DELIVERY_WAITING_ALERT_MINUTES`
  - `page`
- **Sort order**: attention first, then `created_at` ascending.
- **Item**:

```json
{
  "id": 7, "status": "waiting", "attempt": 1, "attention": true,
  "order": {"number": "K7P2QX", "region": "Kinondoni", "street": "Mwenge, near TRA", "contact_name": "Asha",
            "item_count": 3, "total": "45000.00", "paid_at": "2026-11-16T09:12:00Z", "status": "paid"},
  "rider": null, "created_at": "...", "updated_at": "..."
}
```

`rider` has the shape `{"id", "name", "phone", "vehicle"}`.

### `GET /{id}/`

Returns the list item plus:
- `events`: `[{status, attempt, rider, actor_type, actor_name, note, created_at}]`
- `notifications`: `[{kind, attempt, state, outbound_status, created_at}]`
- `failure_reason`

### `GET /{id}/candidates/`

Lists the riders for the assign dialog (FR-007): active riders only, with the assignable ones first.

- **Order**: riders covering the order's region first, then by open-job count.
- **Item**: `{id, name, phone, vehicle, regions: [..], is_available, open_jobs, covers_region}`

### `POST /{id}/assign/`

- **Request**: `{"rider": 12, "expected_status": "waiting", "expected_rider": null}`
- Assigns from `waiting`, or reassigns from `assigned`.
- **200**: the delivery detail.
- **Errors**:
  - **400** `rider_unavailable`: the rider is not assignable.
  - **409** `stale`: the delivery changed; the body includes the current `delivery`.
  - **409** `invalid_transition`: e.g. the parcel is already picked up.

### `POST /{id}/unassign/`

- **Request**: `{"expected_rider": 12}`
- Moves the delivery from `assigned` back to `waiting`. Same errors as assign.

### `POST /{id}/status/`

An admin override for when the rider can't use the phone.

- **Request**: `{"status": "picked_up|on_the_way|delivered|failed", "note": "...", "expected_status": "..."}`
- `note` is required for `failed`.

### `POST /{id}/retry/`

- **Request**: `{"rider": 12 | null}`
- Moves the delivery from `failed` to `waiting` (when `rider` is null) or to `assigned`, with `attempt+1`.

### `POST /api/admin/orders/{number}/delivery/`

Creates a delivery for an order with none (FR-005).

- **201**: the delivery.
- **409** `exists`: the order already has a delivery.
- **400** `not_deliverable`: the status is not `paid` or `processing`.

Cancelling a delivery is not a separate endpoint: the admin cancels the order through the existing order action, and the delivery follows (R3).

## Settings — `/api/admin/delivery-settings/`

- `GET`: returns `{"auto_assign": false, "updated_at": "...", "updated_by": "..."}`
- `PATCH`: takes `{"auto_assign": true}`

## Riders — `/api/auth/riders/` (existing `RiderViewSet`, extended)

The fields change as follows:
- **Added**: `regions` (list of region names, at least one), `preferred_language` (`sw` | `en`), `is_active`, `open_jobs` (read-only), `welcome: {sent_at, state, outbound_status}` (read-only), `legacy_zone` (read-only).
- **Removed from writable fields**: `zone`.
- `password` stays accepted but optional; normally riders set their own through the welcome link.

| Request | Behaviour |
|---|---|
| `POST /` | Creates the user (`role=rider`) and profile, then queues the welcome (R7, R10). 400 if the phone is not valid E.164. 409 `phone_in_use` with `{"can_convert": true\|false}` if the phone belongs to another user. Sending `convert_user: true` converts a non-admin customer instead. |
| `PATCH /{id}/` | Updates fields. `is_active: false` gives 409 `open_jobs` while the rider has active jobs (FR-012). Deactivating also sets `is_available=false`. |
| `POST /{id}/resend-welcome/` | Issues a fresh token and template. Returns 202. Refused with 409 `inactive` for a deactivated rider. |
| `DELETE /{id}/` | Changed to soft-deactivate (same rules as `is_active: false`). Riders with past deliveries are never hard-deleted. |

The list supports `?active=1`, `?available=1` and `?region=`.
