# Implementation Plan: AI Shopping Assistant Core

**Branch**: `003-ai-core` | **Date**: 2026-11-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-ai-core/spec.md`

## Summary

Add a Django app `apps/ai` that indexes products, product images and admin-uploaded knowledge
documents into pgvector + Postgres full-text. It runs a role-scoped tool-calling agent over
self-hosted open models and exposes it as `POST /api/ai/chat`. The agent's tools wrap the existing
cart, checkout, order lookup and Stakaba payment services from 001/002, so prices and orders stay
server-authoritative. Models sit behind env-configured OpenAI-compatible endpoints: Ollama on CPU in
dev, vLLM/TEI on a GPU in prod, plus a small SigLIP2 service for image vectors. Tests use fake
models.

## Technical Context

**Language/Version**: Python 3.14 (backend/.venv); Django 5.2, DRF 3.16

**Primary Dependencies**: existing `openai` 1.109, `pgvector` 0.4.1, `httpx`, Celery, Pillow; new
`pypdf`, `python-docx`. SigLIP service: FastAPI, uvicorn, torch (CPU), transformers

**Storage**: PostgreSQL 16 + pgvector (HNSW cosine), GIN `tsvector`; media for knowledge files and
chat photos (local or S3 via django-storages)

**Testing**: pytest + pytest-django, with fake chat/embedding/image models (research R12). An
opt-in `live_models` marker covers real endpoints

**Target Platform**: Linux containers (app box), and a Windows dev machine with Ollama on CPU

**Project Type**: web service (the existing Django monolith) + one small model-serving sidecar

**Performance Goals**: prod: 90% of text replies ≤ 8 s (SC-005); a product change searchable
≤ 1 min (SC-007). Dev on CPU: ≤ 60 s per reply (functional only)

**Constraints**: ≤ 6 model steps per message; no prices from the model; model-down → fallback
reply with no partial writes; message ≤ 2,000 characters, images ≤ 10 MB

**Scale/Scope**: catalog of hundreds to low thousands of products, tens of knowledge documents,
low hundreds of conversations a day at launch

## Constitution Check

*Checked against constitution v2.0.0, before research and again after design.*

| Principle | How this plan complies | Status |
|---|---|---|
| I. Tanzania-first | Prices are Decimal TZS from the DB; Swahili/English replies with detection (R7); phone normalisation reused from `orders.services` | ✅ |
| II. Server is source of truth | Tool schemas have no price fields; totals come from `cart_totals`/`place_order`; reply `products/cart/order` built from DB rows (R10); orders only after a server-shown summary + confirm (R9) | ✅ |
| III. Self-hosted AI, Stakaba | Only env-configured OpenAI-compatible endpoints + a self-hosted SigLIP; payments via `payments.services.start_payment`; retrieved text wrapped as data | ✅ |
| IV. Verified integrations | No new inbound webhooks. Indexing tasks are idempotent (content hash). Payment retry reuses the existing order | ✅ |
| V. Server-side roles | Tool registry filtered by role and each tool re-checks access; guest conversation token like the cart token; admin endpoints use `IsShopAdmin` | ✅ |
| VI. Test-first | Tests per story are written before the code; models mocked; failure cases (model down, step limit, stock, foreign token, injection) covered | ✅ |
| VII. API-first monolith | One new app in `backend/apps/ai`, endpoints in the drf-spectacular schema. The SigLIP sidecar is justified below | ✅ (see Complexity Tracking) |

Post-design re-check (after data-model/contracts): no new violations.

## Project Structure

### Documentation (this feature)

```text
specs/003-ai-core/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── chat-api.md
│   ├── agent-tools.md
│   └── model-endpoints.md
└── tasks.md            # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── apps/ai/
│   ├── apps.py                 # ready(): connect signals
│   ├── models.py               # Conversation, ChatMessage, KnowledgeDocument, KnowledgeChunk,
│   │                           # ProductIndex, ProductImageIndex
│   ├── migrations/0001_initial.py   # VectorExtension + tables + HNSW/GIN indexes
│   ├── clients.py              # chat/vision/embed/image clients from settings (overridable in tests)
│   ├── language.py             # sw/en detection (R7)
│   ├── indexing.py             # product text builder, hashing, chunking, text extraction
│   ├── search.py               # hybrid_products(), knowledge(), by_image() with RRF
│   ├── tools.py                # tool registry + role filtering + implementations
│   ├── prompts.py              # system prompts (sw/en), data wrapping, fallback strings
│   ├── agent.py                # handle_message() loop, step limit, timeout, audit
│   ├── signals.py              # catalog → on_commit → tasks
│   ├── tasks.py                # index_product, index_product_image, index_document, reindex_all,
│   │                           # purge_old_conversations
│   ├── serializers.py · views.py · urls.py · permissions.py · throttles.py · admin.py
│   ├── testing.py              # FakeChatModel, FakeEmbedder, FakeImageEmbedder
│   ├── management/commands/    # reindex.py, rag_eval.py, ai_check.py
│   ├── eval/                   # catalog.json, cases.json, photos.json, knowledge/, photos/
│   └── tests/                  # test_search, test_indexing, test_tools, test_agent, test_chat_api,
│                               # test_knowledge_api, test_handoff, test_language
├── config/settings.py          # AI_* settings, throttle rates, beat schedule
└── requirements.txt            # + pypdf, python-docx
ai/siglip/                      # Dockerfile, app.py, requirements.txt
infra/docker-compose.yml        # + siglip service (profile "ai"), AI_* env passthrough
infra/docker-compose.gpu.yml    # prod stub: vllm, tei, siglip
.env.example                    # AI_* variables
```

**Structure Decision**: this extends the existing monolith with one app (`backend/apps/ai`),
following the app layout of `orders`/`payments`. Model servers are external processes that the app
reaches over HTTP. No web UI is built in this phase (the optional admin knowledge page is deferred).

## Implementation notes

- **Reuse**: `orders.services` (`add_item`, `set_quantity`, `remove_item`, `cart_totals`,
  `merge_carts`, `place_order`, `normalize_phone`, `delivery_fee_for`, `ShopError` subclasses),
  `orders.views.order_for_phone`, `orders.serializers.CheckoutSerializer` (for guest-detail
  validation), `orders.serializers.CartSerializer` (reply `cart`), `payments.services.start_payment`
  + `payment_message` from `orders.views`, and `accounts.permissions.IsShopAdmin`.
- **Signals and Celery**: use `transaction.on_commit`. Tests rely on `CELERY_TASK_ALWAYS_EAGER` via
  `app.conf.update` (already in `backend/conftest.py`) and `django_capture_on_commit_callbacks`.
- **Agent loop**: build messages → call chat with role tools → for each tool call, validate
  arguments against the JSON schema (no extra keys), run it, append the result → stop on a plain
  text answer or at step 6 → strip `<think>` → save the ChatMessage with the audit trail. Any
  `openai.APIConnectionError`/`APITimeoutError`/`APIStatusError` → `error=model_unavailable` +
  localised fallback.
- **Settings**: `AI_*` from [contracts/model-endpoints.md](contracts/model-endpoints.md);
  `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {"ai_chat": "20/min", "ai_conversation": "10/min"}`;
  beat `ai.purge_old_conversations` daily.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Extra process `ai/siglip` (sidecar service) | Image vectors need a vision encoder; Ollama/vLLM/TEI don't serve SigLIP image embeddings | Loading torch + SigLIP inside Django/Celery would add ~2 GB to every app container and tie model hardware to the app box |
