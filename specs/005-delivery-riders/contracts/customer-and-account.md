# Contract: Customer order view and the set-password page

## Order delivery block (R12, FR-022)

`GET /api/orders/{number}/` (owner) and the existing track lookup return a new read-only field, `delivery`:

```json
"delivery": {
  "status": "on_the_way",
  "rider_first_name": "Juma",
  "rider_vehicle": "motorbike",
  "events": [
    {"status": "assigned", "created_at": "2026-11-16T09:20:00Z"},
    {"status": "picked_up", "created_at": "2026-11-16T09:41:00Z"},
    {"status": "on_the_way", "created_at": "2026-11-16T09:42:00Z"}
  ]
}
```

- The field is `null` when there's no delivery. Rider fields are `null` while the delivery is `waiting`.
- It never contains: rider id, phone, last name, notes, failure reasons, attempts, or other riders.
- `status: "failed"` shows as "Couldn't deliver – we'll contact you". The events from earlier attempts stay.
- **Web**: `components/shop/order-timeline.tsx` merges `delivery.events` with `events` by time. The labels are new keys under `order.delivery.*` in `i18n/{sw,en}.ts`, and the vehicle names come from `order.delivery.vehicles.*`.

## Set-password (R10)

### `POST /api/auth/set-password/`

This endpoint is public and throttled (scope `set_password: 10/hour`).

- **Request**: `{"uid": "<urlsafe b64 user id>", "token": "<token>", "password": "..."}`
- **204**: the password is set. The token is now spent, because the password hash changed.
- **400** `invalid_link`: an expired, used or unknown token or user. One message covers all cases, so the response doesn't reveal which.
- **400** password validator errors in `{"password": [..]}`.
- Only users with `role=rider` and `is_active=True` are accepted for now.

### Web page `/set-password?uid=…&token=…`

This is a shop-route page with no login and no navigation. It has a password field and a confirm field, in sw/en. On success it says "Password set. You'll use it in the rider app." There's no login redirect, because riders have no web screens yet (clarification Q4).

### Setting

`WEB_BASE_URL` (default `http://localhost:3000`) builds the link: `{WEB_BASE_URL}/set-password?uid=…&token=…`.
