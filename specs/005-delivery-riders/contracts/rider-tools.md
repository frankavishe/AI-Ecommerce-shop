# Contract: Rider assistant tools (role `rider`)

The tools are registered in `apps/delivery/rider_tools.py` with `ai.tools.register(..., roles=(RIDER,))`. They're only offered when `handle_message(..., role="rider")` is called (R5, R6). The validation, transactions and data-wrapping are the 003 machinery, unchanged. Every result is a JSON object. `message_sw`/`message_en` keys are not used. **The model does not phrase rider replies**: each tool also sets `ctx.fixed_reply` from `apps/delivery/texts.py`, in the rider's language, and `handle_message` sends that instead of the model's text. (A simulator run on the CPU model showed garbled confirmations and an echoed `<data not_found />`.)

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

## Server commands (no model)

`apps/delivery/rider_commands.py` is a WhatsApp `CONTROL_HANDLERS` step, right after `rider_stop_control`. A rider's text message runs the tool directly through `ai.tools.run_tool` when all of these hold: it has 15 words or fewer, exactly one command matches, and staff haven't taken over the chat. Everything else goes to the model as before.

| Command | Phrases | Tool |
|---|---|---|
| jobs | "kazi zangu", "kazi", "my jobs" | `my_jobs` |
| picked up | "nimechukua", "nimebeba", "picked up" | `update_delivery(picked_up)` |
| on the way | "niko njiani", "on my way" | `update_delivery(on_the_way)` |
| delivered | "nimefikisha", "nimemfikishia", "delivered" | `update_delivery(delivered)` |
| failed | "imeshindikana", "nimeshindwa", "failed": the rest of the text is the reason | `update_delivery(failed, reason)` |
| unavailable / available | "niko off", "not available" / "niko tayari", "available" | `set_availability` |

The order number is an 8-character token from the order alphabet, matched case-insensitively and with or without "#". A lower-case word counts only when it is one of the rider's own jobs. When there's no number: with one active job, it's used. With several, the rider is asked which one and shown the list. With none, the empty-jobs text is sent. The turn is stored as a user message plus an assistant message with `tool_calls` and `steps=0`.

## Fixed texts (server, not model)

These are in `apps/delivery/texts.py`, in sw and en:
- `rider_stop`: "Wewe ni msafirishaji: ujumbe wa kazi hauwezi kuzimwa. Muombe msimamizi akuondoe." / "You are a rider: job messages can't be turned off. Ask the admin to deactivate you."
- The inbox titles: assigned, removed, cancelled.
- Rider replies:
  - the job list (`jobs_text`), or "Huna kazi kwa sasa." when there are none
  - the job details (`details_text`)
  - one text per `update_delivery` outcome: updated (one per status), already, not_found, not_yours_anymore, invalid_transition, reason_required
  - `which_job`, `available_on`, `available_off`
