# Contract: Outbound WhatsApp messages (Graph API) and templates

All calls go to `{WHATSAPP_GRAPH_URL}/{WHATSAPP_GRAPH_VERSION}/...` with
`Authorization: Bearer {WHATSAPP_ACCESS_TOKEN}`. The defaults are `https://graph.facebook.com` and
`v23.0`. Both are configurable, so a version bump is config only. They are wrapped by
`apps/whatsapp/graph.py` (`GraphClient`). Tests replace it with `FakeGraph`.

## Calls used

| Purpose | Request | Response used |
|---|---|---|
| Send any message | `POST /{phone_number_id}/messages` | `messages[0].id` → `wa_message_id` |
| Media info | `GET /{media_id}` | `url`, `mime_type`, `file_size` |
| Media bytes | `GET <url>` (same bearer header) | bytes |
| Upload product photo | `POST /{phone_number_id}/media` (multipart: `file`, `type`, `messaging_product=whatsapp`) | `id` |

## Message bodies

Every body starts with `{"messaging_product": "whatsapp", "recipient_type": "individual", "to": "<wa_id>"}`.

| Kind | Body | Limits | Window |
|---|---|---|---|
| text | `"type":"text","text":{"body":…,"preview_url":true}` | body ≤ 4096 chars (split, R15) | open only |
| image | `"type":"image","image":{"id":<media_id>,"caption":"<name> — <price> TZS"}` | caption ≤ 1024 | open only |
| buttons | `"type":"interactive","interactive":{"type":"button","body":{"text":…},"action":{"buttons":[{"type":"reply","reply":{"id":"confirm:<uuid>","title":"Thibitisha"}},{"type":"reply","reply":{"id":"change:<uuid>","title":"Badilisha"}}]}}` | body ≤ 1024, title ≤ 20, id ≤ 256 | open only |
| template | `"type":"template","template":{"name":…,"language":{"code":"sw"\|"en"},"components":[{"type":"body","parameters":[{"type":"text","text":…},…]}]}` | approved templates only | any time |

The open-window check raises `WindowClosed` before any Graph call (FR-017, SC-006).

## Error classes (R10)

| Class | Examples | Handling |
|---|---|---|
| transient | network error or timeout, HTTP 5xx, Graph codes 1, 2, 4, 80007, 130429, 131016, 131048, 131056 | retry the rest of the batch: up to 4 attempts, countdowns 10 s / 60 s / 300 s |
| permanent (recipient) | 131026 undeliverable/blocked, 131047 re-engagement (window) | the message → `failed`, the rest of the batch → `skipped`, no retry |
| permanent (other) | 100 invalid parameter, 131051 unsupported, 132000–132015 template errors, 190 token expired, other 4xx | `failed` with code and title, logged at ERROR (190 → "check WHATSAPP_ACCESS_TOKEN") |

## Server-built texts

These do not come from the model. The amounts are always from the database and are formatted with
`ai.tools.money` plus a thousands separator.

| Key | Swahili | English |
|---|---|---|
| payment_mobile | "Oda {number}: jumla {total} TZS. Angalia simu yako ({phone}) uweke PIN kukamilisha malipo." | "Order {number}: total {total} TZS. Check your phone ({phone}) and enter your PIN to pay." |
| payment_card | "Oda {number}: jumla {total} TZS. Lipa hapa: {link}" | "Order {number}: total {total} TZS. Pay here: {link}" |
| confirm_body | "Jumla: {total} TZS (pamoja na usafirishaji {fee}). Thibitisha oda?" | "Total: {total} TZS (incl. delivery {fee}). Confirm the order?" |
| summary_outdated | "Kikapu kimebadilika tangu muhtasari ule. Huu ndio muhtasari mpya:" | "Your cart changed since that summary. Here is the new one:" |
| heard | "🎤 Nimesikia: \"{text}\"" | "🎤 I heard: \"{text}\"" |
| voice_retry | "Samahani, sikuweza kusikia vizuri. Tafadhali andika ujumbe au tuma sauti fupi (chini ya dakika 2)." | "Sorry, I couldn't make that out. Please type your message or send a shorter voice note (under 2 minutes)." |
| media_retry | "Samahani, sikuweza kupakua faili. Tafadhali itume tena." | "Sorry, I couldn't download that. Please send it again." |
| image_rejected | "Tafadhali tuma picha ya JPEG, PNG au WebP isiyozidi MB 10." | "Please send a JPEG, PNG or WebP photo up to 10 MB." |
| unsupported | "Ninaweza kusoma ujumbe wa maandishi, picha na sauti tu." | "I can read text messages, photos and voice notes." |
| slow_down | "Unatuma ujumbe mwingi kwa haraka. Tafadhali subiri kidogo." | "You're sending messages very quickly. Please wait a moment." |
| stopped | "Sawa, hutapokea taarifa za oda tena. Tuma ANZA kuziwasha." | "OK, you won't get order updates any more. Send START to turn them back on." |
| started | "Taarifa za oda zimewashwa." | "Order updates are on." |
| cart_pruned | "Karibu tena! Bidhaa hizi hazipatikani tena na zimeondolewa kwenye kikapu: {names}." | "Welcome back! These items are no longer available and were removed from your cart: {names}." |
| link_ok | "Namba hii sasa imeunganishwa na akaunti yako." | "This number is now linked to your account." |
| link_failed | "Samahani, msimbo huo haufanyi kazi. Pata msimbo mpya kwenye ukurasa wa akaunti." | "Sorry, that code didn't work. Get a new one on your account page." |
| link_taken | "Namba hii tayari imeunganishwa na akaunti nyingine." | "This number is already linked to another account." |
| button_expired | "Kitufe hicho kimeisha muda." | "That button has expired." |

## Templates (submitted to Meta outside this feature; category UTILITY)

The names are configurable. Each template exists in `sw` and `en`. The parameters are positional.

| Setting | Default name | Body params | Swahili body (proposal) |
|---|---|---|---|
| `WHATSAPP_TEMPLATE_ORDER_PAID` | `order_paid` | {{1}} number, {{2}} total | "Tumepokea malipo ya oda {{1}} ya {{2}} TZS. Asante! Tutakujulisha ikitoka kwa usafirishaji." |
| `WHATSAPP_TEMPLATE_ORDER_OUT_FOR_DELIVERY` | `order_out_for_delivery` | {{1}} number | "Oda {{1}} iko njiani kukufikia." |
| `WHATSAPP_TEMPLATE_ORDER_DELIVERED` | `order_delivered` | {{1}} number | "Oda {{1}} imefikishwa. Asante kwa kununua nasi!" |
| `WHATSAPP_TEMPLATE_ORDER_CANCELLED` | `order_cancelled` | {{1}} number | "Oda {{1}} imesitishwa. Wasiliana nasi hapa kwa msaada." |
| `WHATSAPP_TEMPLATE_ORDER_EXPIRED` | `order_expired` | {{1}} number | "Muda wa kulipia oda {{1}} umekwisha. Unaweza kuagiza tena hapa." |
| `WHATSAPP_TEMPLATE_FOLLOW_UP` | `follow_up` | (none) | "Habari! Mhudumu wetu anafuatilia ujumbe wako na atakujibu hivi punde." |
