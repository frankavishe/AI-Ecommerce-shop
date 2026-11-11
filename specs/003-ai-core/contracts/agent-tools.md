# Contract: Assistant tools (function-calling schema)

Roles: **guest** (no JWT) and **customer** (JWT, role customer). Admin and rider users chatting in
003 get the customer tool set. Every tool re-checks access on the server, runs in its own
`transaction.atomic()`, and returns JSON. Text from the catalog or documents is wrapped as
`<data source="…">…</data>`.

| Tool | Roles | Arguments | Result / side effects |
|---|---|---|---|
| `search_products` | guest, customer | `query` str, `min_price`? num, `max_price`? num, `category`? str, `in_stock_only`? bool (default true), `limit`? int ≤ 8 | `[{id, name, price, in_stock, category}]` live from the DB; adds them to the reply `products` |
| `get_product` | guest, customer | `product_id` int | full details in the conversation language (description_sw when `sw` and present); inactive → not found |
| `search_by_image` | guest, customer | `note`? str (the shopper's caption) | uses the current message's image; `{caption, used_image_search: bool, products:[…]}`; an error if the message has no image |
| `knowledge_search` | guest, customer | `query` str | top 5 `[{document, text}]` wrapped as data; `[]` when nothing passes the min score |
| `view_cart` | guest, customer | — | the conversation's cart via `cart_totals`; sets reply `cart` |
| `add_to_cart` | guest, customer | `product_id` int, `quantity` int 1–20 | `orders.services.add_item`; `OutOfStock` → `{ok:false, available}` |
| `remove_from_cart` | guest, customer | `product_id` int, `quantity`? int (omit = remove the line) | `set_quantity` / `remove_item` |
| `collect_guest_details` | guest, customer | `name`, `phone`, `region`, `street`, `district`?, `notes`?, `email`? | validated like the checkout serializer; saved to `checkout_details`; returns missing/invalid fields |
| `checkout` | guest, customer | `confirm` bool, `method` `mobile_money`\|`card` (default mobile_money), `network`? | `confirm=false` → the server summary (lines, subtotal, delivery fee for the region, total) and sets `pending_checkout_at`. `confirm=true` → needs a summary within the last 10 min, then `place_order` + `start_payment` (or retries payment on `last_order` if it's `awaiting_payment` and the cart is empty); sets reply `order` + `payment` |
| `order_status` | guest, customer | `order_number` str, `phone`? str | customer: own orders only (or most recent when the number is omitted). Guest: needs a matching phone (`order_for_phone`), otherwise "not found" with no details |
| `handoff_to_human` | guest, customer | `reason` str | `state=needs_human`; reply becomes the fixed notice |

Customer-only behaviour: `collect_guest_details` pre-fills from the user's default saved address
and name/phone.

The model never supplies prices. Any `price`/`total` arguments are not part of the schemas, and
unknown arguments are rejected.
