# Data Model: 003-ai-core

New Django app `backend/apps/ai`. Migration `0001` first runs `pgvector.django.VectorExtension()`
(`CREATE EXTENSION IF NOT EXISTS vector`). Dimensions are settings (`AI_TEXT_DIM=1024`,
`AI_IMAGE_DIM=768`), but a migration fixes them. Changing a dimension needs a new migration and a
`reindex --force`.

## Conversation

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| token | char(64) unique | random `secrets.token_urlsafe(32)`; a guest's proof of ownership |
| user | FK accounts.User null | set for logged-in customers; claimed on first authenticated use |
| cart | FK orders.Cart null, SET_NULL | guest cart (customers use their user cart) |
| channel | enum `api` (default), `whatsapp` (reserved for 004) | |
| language | enum `sw` / `en`, default `sw` | updated per message (research R7) |
| state | enum `active` / `needs_human` | |
| handoff_reason | text blank | |
| checkout_details | JSON default {} | validated guest contact + address (R9) |
| pending_checkout_at | datetime null | set when a checkout summary was shown; needed before confirm |
| last_order | FK orders.Order null | reused when a payment start must be retried |
| created_at / updated_at | datetime | `updated_at` drives idle expiry and the 90-day purge |

Rules: guest access needs the `token` **and** `user is null` (or the same user). A customer only
ever sees conversations where `user == request.user`. Index on `(state, updated_at)`.

State transitions: `active → needs_human` (tool `handoff_to_human`), `needs_human → active`
(admin release only).

## ChatMessage

| Field | Type | Notes |
|---|---|---|
| id | bigint PK | |
| conversation | FK Conversation CASCADE | |
| role | enum `user` / `assistant` / `system_note` | `system_note` = handoff notices, fallbacks |
| text | text | the shopper's text, or the final reply with `<think>` removed |
| image | ImageField null (`ai/chat/%Y/%m/`) | shopper photo; deleted after 30 days |
| image_deleted | bool | |
| language | enum sw/en | |
| tool_calls | JSON default [] | `[{name, arguments, ok, result_summary, ms}]` audit trail (FR-006) |
| payload | JSON default {} | structured `products` / `cart` / `order` / `payment` returned to the client |
| steps | small int | model calls used (≤ 6) |
| latency_ms | int null | |
| error | char blank | `model_unavailable`, `step_limit`, `timeout`, … |
| created_at | datetime | ordering |

History sent to the model: the last `AI_HISTORY_MESSAGES` (default 12) user/assistant texts,
plus a compact note of the tools used, not their full results.

## KnowledgeDocument

| Field | Type | Notes |
|---|---|---|
| id | bigint PK | |
| title | char(200) | defaults to the file name |
| file | FileField (`ai/knowledge/`) | PDF/DOCX/TXT/MD, ≤ 10 MB |
| content_type | char | detected type |
| language | enum `sw` / `en` / `mixed` | detected (R7), can be overridden |
| status | enum `processing` / `ready` / `failed` | |
| error | text blank | e.g. "no extractable text" |
| chunk_count | int | |
| uploaded_by | FK User SET_NULL | |
| created_at / indexed_at | datetime | |

Deleting a document cascades to its chunks and removes the file (`post_delete`).

## KnowledgeChunk

| Field | Type | Notes |
|---|---|---|
| id | bigint PK | |
| document | FK KnowledgeDocument CASCADE | |
| position | int | order within the document |
| text | text | ~1,800 characters (R6) |
| embedding | vector(1024) | HNSW `vector_cosine_ops` |
| tsv | SearchVectorField | GIN; `simple` config |

Unique `(document, position)`.

## ProductIndex (1:1 with catalog.Product)

| Field | Type | Notes |
|---|---|---|
| product | OneToOne PK → Product CASCADE | |
| text | text | index text: name, category (en+sw) + parent, tags, attributes, descriptions |
| content_hash | char(64) | sha256 of `text`; skips re-embedding when unchanged |
| text_vec | vector(1024) null | HNSW cosine |
| tsv | SearchVectorField | GIN; weights A name/category, B tags/attributes, C descriptions |
| status | enum `pending` / `ready` / `failed` | |
| error | text blank | |
| indexed_at | datetime null | |

Search reads `is_active`, `stock`, `price` and `category` live from `Product` (JOIN), never from
the index, so prices are always current.

## ProductImageIndex (1:1 with catalog.ProductImage)

| Field | Type | Notes |
|---|---|---|
| image | OneToOne PK → ProductImage CASCADE | |
| product | FK Product CASCADE | denormalised for the search JOIN |
| image_vec | vector(768) null | HNSW cosine |
| status / error / indexed_at | as above | |

## Evaluation files (not DB)

`apps/ai/eval/cases.json`: `[{"id", "kind": "product"|"knowledge", "lang": "sw"|"en", "query",
"filters"?, "expect": ["<product sku>" | "<document title>"]}]`.
`apps/ai/eval/photos.json`: `[{"file", "expect": ["<sku>"]}]`. See research R15.

## Relationships to existing apps

- `orders.Cart` ← Conversation.cart (guest); customers use `Cart(user=…)`.
- `orders.Order` ← Conversation.last_order. Orders are created only by `orders.services.place_order`.
- `payments.Payment` is created only by `payments.services.start_payment`.
- `catalog.Product` / `ProductImage` / `Category` signals → indexing tasks (R5).
