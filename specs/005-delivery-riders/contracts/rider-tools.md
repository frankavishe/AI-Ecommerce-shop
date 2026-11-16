# Contract: Rider assistant tools (role `rider`)

The tools are registered in `apps/delivery/rider_tools.py` with `ai.tools.register(..., roles=(RIDER,))`. They're only offered when `handle_message(..., role="rider")` is called (R5, R6). The validation, transactions and data-wrapping are the 003 machinery, unchanged. Every result is a JSON object. `message_sw`/`message_en` keys are not used; the model phrases the reply from the fields, in the rider's language.

## Shared rules

- The caller is always `ctx.user`, an active rider. A tool never accepts a rider id from the model.
- A job lookup uses `Delivery(order__number=<normalized upper-case number>, rider=ctx.user, status ∈ open)`. A miss returns `{"ok": false, "error": "not_found"}`. That's the same result for a missing order, someone else's order and a closed job (FR-016).
- Status writes go through `delivery.services.change(...)` with `expect` set to the rider. If the job was moved meanwhile, the result is `{"ok": false, "error": "not_yours_anymore"}`.

## `my_jobs()`

- **Arguments**: none.
- **Result**:

```json
{"ok": true, "jobs": [
  {"order_number": "K7P2QX", "status": "assigned", "region": "Kinondoni", "street": "Mwenge, near TRA",
   "contact_name": "Asha", "assigned_at": "2026-11-16T09:20:00+03:00"}
]}
```

Only active jobs (`assigned`, `picked_up`, `on_the_way`) are listed, oldest first, with at most 10.

## `job_details(order_number: string)`

```json
{"ok": true, "order_number": "K7P2QX", "status": "picked_up", "contact_name": "Asha",
 "contact_phone": "+255712345678", "region": "Kinondoni", "district": "Kinondoni", "street": "Mwenge, near TRA",
 "notes": "Call on arrival", "items": [{"name": "Viatu vyekundu", "quantity": 1}], "paid": true}
```

`notes` is customer-written text. It's passed to the model inside the data wrapper, never as instructions (FR-026).

## `update_delivery(order_number: string, status: enum, reason?: string)`

- `status` must be one of `picked_up`, `on_the_way`, `delivered` or `failed`.
- `reason` is required for `failed`, with a maximum of 255 characters.
- **Results**:
  - `{"ok": true, "status": "delivered", "recorded": ["picked_up", "delivered"]}`
  - `{"ok": true, "status": "delivered", "already": true}`: a repeat. Nothing changes and no one is notified (FR-017).
  - `{"ok": false, "error": "invalid_transition", "current": "delivered"}`: a backwards move.
  - `{"ok": false, "error": "reason_required"}`
- The tool is `mutates=True`, so the 003 fallbacks list it as done when the model then fails.

## `set_availability(available: boolean)`

- **Result**: `{"ok": true, "available": false, "active_jobs": 1}`
- Going unavailable doesn't touch current jobs; it only stops new assignments.

## Rider system prompt

The prompt is short, in sw and en. It says:
- You help this rider with their delivery jobs, using these tools only.
- Never make up order numbers, phones or addresses.
- For anything else (prices, orders, complaints), tell the rider to contact the shop admin.
- Confirm every status change in one short sentence.
- Ask for the order number when the rider has more than one active job and didn't say which.

When there is exactly one active job and the rider omits the number, the model may use it after `my_jobs`. The tools themselves always require `order_number`.

## Fixed texts (server, not model)

These are in `apps/delivery/texts.py`, in sw and en:
- `rider_stop`: "Wewe ni msafirishaji: ujumbe wa kazi hauwezi kuzimwa. Muombe msimamizi akuondoe." / "You are a rider: job messages can't be turned off. Ask the admin to deactivate you."
- The inbox titles: assigned, removed, cancelled.
