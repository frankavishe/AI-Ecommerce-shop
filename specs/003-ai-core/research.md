# Research: 003-ai-core

All Technical Context unknowns are settled below. Each entry gives Decision / Rationale / Alternatives.

## R1. Model access

- **Decision**: Use one `openai` SDK client factory (`apps/ai/clients.py`) for chat, vision and text
  embeddings, with base URL, model and key taken from env. Dev uses Ollama's OpenAI-compatible
  `/v1` (chat `qwen3:4b`, vision `qwen2.5vl:3b`, embeddings `bge-m3`). Prod uses vLLM (Qwen3-VL-8B,
  which handles chat and vision as one model) and TEI (`bge-m3`, OpenAI-compatible
  `/v1/embeddings`). Image vectors come from a small HTTP service (R4) through `httpx`.
- **Rationale**: Constitution III says switching between dev and prod is config-only. `openai`
  is already pinned in `requirements.txt`. Ollama, vLLM and TEI all serve the same API shape.
- **Alternatives**: LangChain/LlamaIndex (a large dependency for a ~6-tool loop, and it hides the
  safety checks). llama.cpp server (works too, and fits behind the same env vars).

## R2. Tool calling and Qwen3 "thinking"

- **Decision**: Native OpenAI `tools` / `tool_calls`, with at most 6 model calls per message
  (`AI_MAX_STEPS=6`). For Qwen3, `AI_CHAT_NO_THINK=true` appends `/no_think` to the system prompt,
  and any `<think>…</think>` text is removed from replies. If a tool call has malformed JSON, the
  error goes back to the model as a tool result. That counts as a step.
- **Rationale**: Ollama and vLLM (`--enable-auto-tool-choice --tool-call-parser hermes`) both
  support tool calls for Qwen. Thinking mode makes CPU replies 3–5× slower for no benefit here.
- **Alternatives**: JSON-mode "ReAct" text parsing (more fragile); grammar-constrained decoding
  (not portable across servers).

## R3. Hybrid product and knowledge search

- **Decision**: Two candidate lists of 50 each, fused with Reciprocal Rank Fusion (k=60):
  1. pgvector cosine distance on `text_vec vector(1024)`, with an HNSW index (`vector_cosine_ops`).
  2. Postgres full-text on a stored `tsvector` built with the `simple` config (it works for both
     Swahili and English, since Postgres has no Swahili stemmer), with weights: name/category A,
     tags/attributes B, descriptions (en+sw) C. Queried as an OR of prefix terms
     (`red:* | shoes:* | …`, raw `to_tsquery`), so a long shopper sentence still matches; `ts_rank`
     orders the hits. (Changed from `websearch_to_tsquery` during US1: its AND semantics missed
     "red shoes under 50000".) The vector list also has a cutoff (`AI_PRODUCT_MIN_SIMILARITY`,
     default 0.3) so nonsense queries return nothing; `rag_eval` tunes it.
  Filters (`is_active`, `stock>0`, price range, category including children) are applied in both
  SQL queries, before fusion. Prices are always read from `Product` rows after fusion.
- **Rationale**: Meaning-based search handles "viatu vyekundu" → "red sneakers" across languages
  (bge-m3 is multilingual), while keyword search catches SKUs, brands and exact names. RRF needs no
  score tuning.
- **Alternatives**: Vector-only search (misses SKUs and brands); a separate search engine like
  Meilisearch or Elasticsearch (another service, against Constitution VII).

## R4. Image (photo) search

- **Decision**: `ai/siglip/` is a FastAPI service (`POST /embed/image` multipart → `{"embedding":
  [768 floats]}`, `GET /health`) running `google/siglip2-base-patch16-224` on CPU torch, with
  L2-normalised vectors. Each `ProductImage` gets a `ProductImageIndex(image_vec vector(768))` with
  HNSW. A shopper photo goes through two searches: (a) the SigLIP vector → nearest images → products,
  best image per product; (b) the vision model captions the photo in English (short attribute list)
  → caption + shopper caption → hybrid text search. The two lists are fused with RRF, image list
  first. If SigLIP is down, (b) runs alone and the reply says so. If the vision model also fails,
  only the shopper's caption is searched.
- **Rationale**: SigLIP2 base is small (~375 MB) and runs fast enough on CPU for a dev catalog.
  The same service image is used on the GPU box.
- **Alternatives**: Vision-model captions only (loses visual similarity); CLIP ViT-B/32 (weaker
  multilingual and retrieval quality); embedding images with the chat VLM (not supported by the
  servers).

## R5. Indexing triggers

- **Decision**: `post_save`/`post_delete` signals on `Product`, `ProductImage` and `Category` call
  `transaction.on_commit(lambda: index_product.delay(id))`. The task builds the index text, hashes
  it (`content_hash`) and calls the embedder only when the hash changed, so stock-only changes skip
  re-embedding. Price and stock live on `Product` and are read when searching, so they are always
  current (SC-007). Inactive or deleted products are filtered out or cascade-deleted. A failure
  sets `status=failed, error=…`, retries 3 times with backoff, and shows in the admin index-status
  list. `manage.py reindex [--products] [--knowledge] [--force]` and the admin "reindex" endpoint
  queue the same tasks.
- **Rationale**: Saves never wait on the model (FR-019). The hash avoids pointless embedding calls.
- **Alternatives**: A cron re-index (stale for minutes, which breaks SC-007); embedding inside the
  request (slow, and fails when the model is down).
- **Test note**: tests set `CELERY_TASK_ALWAYS_EAGER` through `app.conf.update` (see
  `backend/conftest.py`). `on_commit` needs `django_capture_on_commit_callbacks` or
  `transaction=True` tests.

## R6. Knowledge documents

- **Decision**: Accept PDF (`pypdf`), DOCX (`python-docx`) and TXT/MD (UTF-8, falling back to
  latin-1), up to 10 MB. Text is normalised and split on paragraph boundaries into ~1,800-character
  chunks (~450 tokens) with 300-character overlap. Each chunk gets `embedding vector(1024)` +
  `tsv`. Documents with no text (scanned PDFs) are marked `failed` with "no extractable text".
  Deleting a document removes its chunks and file. Search is hybrid (R3), top 5 chunks.
- **Alternatives**: OCR for scanned PDFs (deferred); token-exact chunking with a tokenizer
  (another dependency, and the gain is small).

## R7. Language detection

- **Decision**: A small built-in heuristic (`apps/ai/language.py`) that scores against a list of
  ~150 common Swahili words and markers (ni, na, kwa, nataka, bei, gani, viatu, -ni suffixes,
  habari…) versus English stopwords. The winner becomes the conversation language. On a tie or a
  very short message, the previous language is kept (default `sw`). The system prompt tells the
  model which language to reply in.
- **Rationale**: Only two languages, no dependency, and testable without a model.
- **Alternatives**: `langdetect`/`fasttext` (weak Swahili accuracy on short texts, plus a large
  model file); asking the LLM (costs a step).

## R8. Conversation identity and cart linkage

- **Decision**: `POST /api/ai/chat` with no `conversation` token creates a `Conversation`. A guest
  gets a random 43-character token and a new guest `Cart` linked to the conversation. The response
  returns `conversation_token` and `cart_token`, so the same cart works with `X-Cart-Token` in the
  web shop (FR-013). A logged-in customer's conversation uses their user cart
  (`Cart.objects.get_or_create(user=…)`). If a guest conversation is continued by a logged-in user,
  it is claimed and its cart merged with `orders.services.merge_carts`. Guest conversations expire
  after `GUEST_CART_LIFETIME`, like the guest cart.
- **Rationale**: Reuses the 001 cart rules unchanged and ties directly into the web shop.

## R9. Checkout inside chat

- **Decision**: Tools `collect_guest_details` (name, phone, region, street, district?, notes?,
  email?) validate with the existing checkout serializer and store the details in
  `Conversation.checkout_details`. `checkout(confirm: bool, method: mobile_money|card,
  network?)`: when `confirm` isn't true, it returns the server-computed summary (lines, subtotal,
  region fee, total) for the model to show. When `confirm=true`, it calls
  `orders.services.place_order` and then `payments.services.start_payment`. Mobile money (the
  default) sends a USSD prompt to the phone, so the reply says to check the phone. Card returns
  Stakaba's hosted `checkout_link`. The order is stored on the conversation. If the payment start
  fails, the next checkout call reuses that `awaiting_payment` order (it doesn't place a new one)
  and calls `start_payment` again, the same way as `OrderPayView`.
- **Rationale**: Both payment rails already exist and are tested. "Payment link" in the spec means
  the Stakaba checkout, which for mobile money is a phone prompt and not a URL.
- **Confirmation**: the server only places the order when `confirm=true` **and** the previous
  assistant turn showed a checkout summary (stored `pending_checkout_at`). This stops a single
  injected message from placing an order without a summary being shown first.

## R10. Safety rules

- Tool results come from the DB. The API reply also carries structured `products`, `cart` and
  `order` objects built by the server from tool results, not parsed from model text. Clients
  render prices from these objects.
- Retrieved passages and product text go into tool results wrapped as
  `<data source="…">…</data>`. The system prompt says the content inside is untrusted data.
- The tool registry is filtered by role (`guest`, `customer`). Each tool also checks access itself
  (e.g. `order_status` uses `order_for_phone` for guests and `user=request.user` for customers).
- Model or tool exceptions roll back their own transaction (each tool runs in `atomic()`), so no
  action is half-applied. Actions completed earlier in the turn stay (a started payment can't be
  undone), and the localised fallback lists them from `tool_calls` (FR-005, SC-008).

## R11. Synchronous chat request

- **Decision**: `POST /api/ai/chat` runs the agent inside the request (timeout `AI_CHAT_TIMEOUT`,
  default 90 s on dev, 20 s on prod). The core is a plain service
  `agent.handle_message(conversation, text, image) -> AgentReply`, so 004 can call it from a Celery
  task for WhatsApp.
- **Alternatives**: async jobs with polling (more client work, and no client exists yet).

## R12. Testing without models

- **Decision**: `apps/ai/testing.py` provides:
  - `FakeChatModel`: scripted responses (tool calls, then text), used through the
    `clients.get_chat_client` override fixture. It records the messages it received, so tests can
    check the prompt (language, data-wrapping).
  - `FakeEmbedder`: a deterministic hashed bag-of-words of 1024 dims with a small sw↔en synonym
    table, L2-normalised. Similar text gets nearby vectors, so search ranking tests mean something.
  - `FakeImageEmbedder`: 768-d from a colour histogram, so a re-shot of the same synthetic picture
    lands nearest.
  - Marker `live_models` (opt-in, like `sandbox`) runs a few smoke tests against the configured
    real endpoints.
- **Rationale**: Constitution VI says model servers are mocked in default runs.

## R13. Rate limits and input limits

- **Decision**: DRF `ScopedRateThrottle` scope `ai_chat` = `20/min` (per user or IP), plus a
  per-conversation throttle of `10/min`. Message limit 2,000 characters, image ≤ 10 MB, Pillow
  verifies JPEG/PNG/WebP and downsizes to 1024 px before sending to models. Knowledge uploads are
  ≤ 10 MB.

## R14. Retention

- **Decision**: A Celery beat task `ai.purge_old_conversations` runs daily. It deletes
  conversations idle for more than 90 days and shopper images older than 30 days (the file is
  removed and the message keeps `image_deleted=true`).

## R15. Evaluation set

- **Decision**: `backend/apps/ai/eval/` holds `catalog.json` (seed products, ~40), `cases.json`
  (≥ 50 text cases: `{query, lang, expect_products | expect_document}`), `knowledge/` (sample
  policy TXT files) and `photos/` (query photos, with `photos.json` mapping to the expected
  product). `manage.py rag_eval [--seed] [--kind products|knowledge|photos]` loads the seed data
  into the current DB (only with `--seed`, and refuses unless `DEBUG`), indexes it, runs the cases
  through the same search functions the tools use, and prints hit-rate@5 per kind and language.
  It exits non-zero when below `--min` thresholds. Seed product images and photos are user-provided
  or generated locally. The command skips photo cases whose files are missing and reports them.

## R16. Human handoff

- **Decision**: The `handoff_to_human(reason)` tool sets `Conversation.state=needs_human` and
  `handoff_reason`. While in that state, `/api/ai/chat` stores the shopper's message and replies
  with a fixed localised "a staff member will reply" without calling the model. Admin endpoints:
  `GET /api/ai/admin/conversations/?state=needs_human` and `POST …/{id}/release/`.
