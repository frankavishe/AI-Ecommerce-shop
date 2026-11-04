# AI Ecommerce Shop Constitution

## Core Principles

### I. Tanzania-First Commerce

- All money is Tanzanian Shillings (TZS), stored and computed as `Decimal` (never `float`).
- All timestamps are timezone-aware; business time is `Africa/Dar_es_Salaam`.
- Phone numbers are stored and compared in E.164 format (`+255...`).
- Customer-facing text MUST support Swahili and English.

Rationale: the shop serves the Tanzanian market, where mobile money and phone numbers are the
primary customer identity and payment rails.

### II. Server Is the Source of Truth

- Prices, discounts, delivery fees and totals MUST be computed on the server from the database.
  Values sent by a client (web, app) or produced by an LLM MUST be ignored for pricing.
- Payment/checkout requests MUST be built only from server-side cart or order state.
- Stock changes MUST be atomic (row locks or conditional updates) so concurrent orders cannot
  oversell.

Rationale: every channel (web, Android, WhatsApp AI) is untrusted input; money and stock
integrity cannot depend on it.

### III. Self-Hosted AI, Local Payment Rails

- AI features MUST use self-hosted open models behind OpenAI-compatible endpoints configured by
  environment variables. Proprietary hosted AI APIs MUST NOT be introduced.
- Payments MUST go through ClickPesa (mobile money + cards). Alternative gateways require a
  constitution amendment.
- Retrieved/user-supplied content passed to an LLM MUST be treated as data, never instructions.

Rationale: no dependency on foreign AI vendors; ClickPesa covers M-Pesa, Tigo Pesa, Airtel Money,
HaloPesa and cards.

### IV. Verified, Idempotent Integrations

- Every inbound webhook (ClickPesa, WhatsApp) MUST verify its signature/checksum and reject
  invalid requests.
- Webhook handling MUST be idempotent: replays of the same event MUST NOT change state twice.
- Payment status MUST be confirmed against the provider (status query) and the paid amount MUST
  match the order total before an order is marked paid.
- Webhook endpoints SHOULD respond quickly and push slow work to Celery.
- Secrets live in `.env` only and MUST NOT be committed.

Rationale: webhooks are public endpoints and are retried by providers.

### V. Role-Based Access Enforced Server-Side

- Roles are `customer`, `admin`, `rider` (plus anonymous guests). Every endpoint, task and AI tool
  MUST check permissions on the server.
- Guests may only reach their own data via a secret (cart token) or a matching proof
  (order number + phone).

Rationale: the same backend serves web, app and AI agents; the client cannot be trusted to hide
actions.

### VI. Test-First (NON-NEGOTIABLE)

- New behaviour starts with failing `pytest`/`pytest-django` tests, then implementation.
- External services (ClickPesa, WhatsApp, model servers) MUST be mocked in automated tests.
- Money, stock, permissions and webhook paths MUST have tests for the failure cases, not only the
  happy path.

Rationale: money and stock bugs are expensive and hard to undo.

### VII. API-First, Simple Monolith

- The Django REST Framework API, documented through drf-spectacular OpenAPI, is the contract the
  Next.js web and Flutter app consume. New endpoints MUST appear in the generated schema.
- One Django project with focused apps under `backend/apps/` (models, serializers, views, urls,
  admin, tests). No microservices until a measured need exists (YAGNI).

Rationale: a single small team; one well-documented API keeps three clients consistent.

## Technology Constraints

- Backend: Python, Django 5, DRF, simplejwt, Celery + Redis, PostgreSQL 16 + pgvector.
- Web: Next.js (App Router, TypeScript). Mobile: Flutter (Android).
- Messaging: Meta WhatsApp Cloud API. Payments: ClickPesa.
- AI: vLLM (Qwen3-VL), TEI (bge-m3), SigLIP2, faster-whisper on a rented GPU box.
- Local development runs through `infra/docker-compose.yml`.

## Development Workflow

- Work is driven by Spec Kit: `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` →
  `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement`, one feature branch per spec.
- Each feature's `plan.md` MUST include a Constitution Check against these principles.
- Before merging: `pytest` passes, `python manage.py makemigrations --check` reports no drift, and
  the OpenAPI schema generates without errors.
- Commits use Conventional Commit messages.

## Governance

This constitution supersedes other practices for this repository. Amendments are made by editing
this file through `/speckit-constitution`, with a version bump: MAJOR for removing or redefining a
principle, MINOR for adding a principle or materially expanding guidance, PATCH for wording fixes.
Every plan and review checks compliance; any deviation MUST be recorded with its justification in
the plan's Complexity Tracking table. Runtime guidance for agents lives in `CLAUDE.md` and the
`.claude/skills/speckit-*` skills.

**Version**: 1.0.0 | **Ratified**: 2026-10-28 | **Last Amended**: 2026-10-28
