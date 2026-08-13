# Backend Migration Plan — `agente_fiscal` (Python/FastAPI)

> Status: **Draft — planning**
> Target stack: keep **Python + FastAPI** (it works today)
> Monorepo layout: `frontend/` (Next.js UI, exists) + `backend/` (migrated Python service)

---

## 1. Objective

Migrate the existing fiscal agent backend (the archived legacy backend, package `agente_fiscal`)
into the monorepo so it becomes the real backend for the Next.js frontend (`frontend/`).

> Cutover Phase 5 (completed): the legacy backend folder was archived/deleted. Its
> business data (API keys/apps/plans/developers/tenant admin CRUD) now lives in
> Postgres behind hexagonal ports (`agente_fiscal.ports.api_keys`,
> `agente_fiscal.ports.clients`); Redis remains rate-limit/cache + best-effort
> conversations. The legacy `/v1/admin/tenants` (single "Estudio Contable" with
> its own CUIT/clave_fiscal) was retired outright — its real equivalent, the
> CUIT clients a tenant manages, is now `/v1/clients` over the existing
> `clients` table (already wired to `report_runs.client_id`).

The migration is **incremental (strangler fig)** — never a big-bang rewrite.

### What is already done (do NOT re-implement)

| Concern | Where it lives today |
|---|---|
| Authentication (Clerk) | `frontend/` + `backend/db/schema.ts` (User) — Clerk JWT already verified in routes |
| Tenants / TenantMembers | `backend/db/schema.ts` — `Tenant`, `TenantMember`, `Chat` models exist |
| Chat history / messages | `backend/db/` queries + `frontend/app/(chat)/api/chat/` |

The Python service must **consume** the existing auth/tenant context (Clerk JWT → `userId` + `tenantId`)
instead of shipping its own tenant store (`api/store.py` Redis tenants) into production.

### The migration target in one sentence

> `frontend/` (Vercel serverless) calls `backend/` (FastAPI in a container) via HTTP;
> long-running fiscal pipelines run as async jobs (queue + worker), not inside a web request.

---

## 2. Current state of the legacy backend

- **Stack**: FastAPI 2.0.0, Pydantic v2, Typer CLI, Redis (`redis.asyncio`) as the **main data store**,
  Engram (HTTP `localhost:7437`) as per-CUIT memory, ReportLab PDFs, SMTP email, Composio cloud browser.
- **~88 Python files / ~10.8k lines**, 13 test files (~3k lines).
- **No SQL database, no queue system, no Dockerfile, no requirements.txt/pyproject.toml in repo.**
- Pipeline (`pipeline/service.py`) is **synchronous**: Padrón A5 (SOAP) → browser (minutes) → PDF → email, all inside one request.

### Module risk map

| Module | Responsibility | Migration risk |
|---|---|---|
| `rules_engine.py` | Deterministic ARCA calendar (CUIT-ending tables, feriados.csv, idImpuesto map) | **Low** — pure Python |
| `billing/tiers.py` | Plan rules + cost per browser second | **Low** — pure logic |
| `chat/` | Intent detection + Spanish response formatting | **Low** — pure logic |
| `matching.py` | IIBB / Convenio Multilateral matching | **Low** |
| `models.py` | ~45 Pydantic models | **Low** — port to new schema |
| `email_sender.py` | SMTP send with PDF attachment | **Low-Med** |
| `memory/` | Engram client + TenantBrain context | **Med** — external service |
| `api/store.py` | Redis tenants/keys/plans/conversations | **Med** — replaced by SQL for business data |
| `api/` (routes, middleware) | FastAPI: auth dual, rate limit, chat/extract/report | **Med-High** — HTTP layer |
| `pdf_generator.py` | ReportLab A4 multipage PDF | **Med** — heavy, keep as worker concern |
| `arca_ws.py` | WSAA + Padrón A5/A13 SOAP, certs, openssl | **High** — SOAP + certs + binary |
| `browser/` (Composio) | Cloud browser tasks (debt, facilidades, registro, IIBB) | **High** — external API, minute-long tasks |
| `pipeline/service.py` | Orchestration heart, shared singleton | **High** — becomes async job |

---

## 3. Target architecture

```
┌────────────────────────────────────────────────────────────┐
│ Browser / UI                                                │
│  frontend/ (Next.js on Vercel, serverless)                  │
│    - Clerk auth (exists)                                    │
│    - Chat + fiscal report UI (exists)                       │
└───────────────────────────┬────────────────────────────────┘
                            │ HTTPS /api/*
                            ▼
┌────────────────────────────────────────────────────────────┐
│ backend/ (FastAPI, Docker container — Fly.io / Railway)     │
│  web process:                                               │
│    - /health, /api/chat, /api/report (light endpoints)      │
│    - Auth: Clerk JWT (userId + tenantId)                    │
│  worker process:                                            │
│    - queue consumer (Redis Streams / RQ / BullMQ-style)     │
│    - runs fiscal pipeline: Padrón A5 → browser → PDF → mail │
│  cron process (optional):                                   │
│    - batch calendar runs from clients.yaml                  │
└──────┬───────────────────┬──────────────────┬───────────────┘
       │                   │                  │
       ▼                   ▼                  ▼
   PostgreSQL          Redis             S3/R2
   (Neon/Supabase)     (Upstash)         (PDF files)
   - tenants/users     - rate limit      - generated PDFs
   - clients           - TA cache
   - report_runs       - JWKS cache
   - conversations     - queues
   - billing_events
```

### Key principles

1. **Business data → Postgres.** Redis stops being the source of truth for tenants, keys, plans, conversations.
2. **Redis stays** for rate limiting, ARCA TA cache, JWKS cache, and (new) **the job queue**.
3. **The pipeline is a job, not a request.** HTTP endpoints enqueue; workers execute; `report_runs` tracks state (this feeds the existing frontend "history" UI).
4. **Auth/tenants are not rebuilt.** The Python API trusts Clerk JWTs verified by `frontend/`; it receives `userId`/`tenantId` per request and scopes everything by `tenantId`.
5. **No state on the web container filesystem.** Certs are secrets; PDFs go to object storage.

---

## 4. Data model (PostgreSQL)

Single schema, versioned migrations (Alembic for SQLAlchemy, or a migration tool of your choice).

### Core (replaces Redis-owned business data)

- `tenants` — id (UUID v7), name, clerk_org_id, created_at, updated_at
  - *mirror of existing `backend/db/schema.ts` Tenant; seed from Clerk orgs*
- `users` — id, clerk_user_id, email, display_name, created_at
- `tenant_members` — tenant_id, user_id, role (mirror of `TenantMember`)
- `api_keys` — id, tenant_id, key_hash (sha256), name, created_at, last_used_at, revoked_at
  - *migrate from Redis `tenant:apikey:*`; store hash only, never plaintext*
- `apps` — id, tenant_id, developer_id, name, created_at
- `plans` — id, tenant_id, tier (free/pro/pro_max/enterprise), status, period, created_at
- `conversations` — id, tenant_id, user_id, title, status, created_at, updated_at
  - *replaces Redis `tenant:{tid}:conv:*`; keep the frontend's camelCase contract*
- `messages` — id, conversation_id, role, parts (JSONB), created_at

### Business domain

- `clients` — id, tenant_id, cuit (unique per tenant), name, email, config (JSONB)
  - *migrate from `clients.yaml` — becomes per-tenant data, not a global file*
- `report_runs` — id, tenant_id, client_id, cuit, status (queued|running|done|failed), steps (JSONB), result_summary (JSONB), started_at, finished_at, error (JSONB)
  - **NEW — this is the audit trail** the frontend already displays as "history"
- `generated_pdfs` — id, report_run_id, storage_key (S3/R2), filename, size_bytes, created_at
  - *binary never goes to SQL — reference only*
- `billing_events` — id, tenant_id, plan_id, description, amount, currency, created_at

### Static rules (decide once)

- `feriados` (from `feriados.csv`) and `calendario_afip` (from JSON):
  - If they change over time → seed as versioned tables.
  - If static for the product's lifetime → keep as repo assets (`backend/data/`) and load at boot.
  - Default recommendation: **repo assets** first, promote to tables only when updates are needed at runtime.

### Identities & conventions

- UUID **v7** for all primary keys (time-ordered, index friendly).
- `created_at`/`updated_at` as `timestamptz`.
- **No soft deletes** unless a business rule requires it; hard delete + audit log instead.
- Enums as PostgreSQL `TEXT` + CHECK or native `ENUM` — pick one, keep it consistent.

---

## 5. Redis — what stays, what goes

| Role | Today | After migration |
|---|---|---|
| Business data (tenants, keys, plans, conversations) | Redis (source of truth) | **PostgreSQL** |
| Rate limiting (sliding window Sorted Sets) | Redis | **Redis** (keep) |
| ARCA TA cache (token+sign, ~12h TTL) | In-memory singleton | **Redis** (shared across processes) |
| Clerk JWKS cache | Redis | **Redis** (keep) |
| Per-CUIT memory cache (Engram cache) | Redis | **Redis** (keep) |
| **Job queue** | none | **Redis Streams** (new) |

**Conclusion: Redis is still required**, but only as cache/rate-limit/queue — no longer as the database.
Use Upstash (serverless) or the provider-managed Redis on your container host.

---

## 6. Async pipeline (the core redesign)

Today: `PipelineService.run_pipeline()` does everything synchronously inside a request.

Target:

1. `POST /api/report { tenantId, cuit, email }` (light, <100ms) → validates → creates `report_runs` row (status=queued) → enqueues job → returns `{ runId }`.
2. **Worker** consumes the job and executes:
   - Padrón A5 (SOAP/ARCA) → update run (steps)
   - Browser (Composio) tasks → update run (steps)
   - PDF generation → upload to S3/R2 → insert `generated_pdfs`
   - Email send (SMTP)
   - Mark run done/failed with error details
3. Frontend polls `GET /api/report/{runId}` (or SSE/WebSocket) to render progress and final state.

Recommended queue options (keep Python):
- **RQ** (simple, Redis-backed, enough for a single worker) — fastest to adopt.
- **Celery** (feature-rich: beat scheduler for cron, retries, visibility timeout) — more ops weight.
- **Redis Streams + asyncio consumer** (lightweight, you already use `redis.asyncio`) — if you want full control.

Recommendation: start with **RQ or a small asyncio Streams consumer**; add Celery only if you need its scheduler/retry machinery.

### What this unlocks

- The web container never blocks on a 5-minute browser task.
- Retries and visibility timeouts become first-class.
- `report_runs` gives you the history/audit trail the frontend can display.
- The existing CLI batch mode (`python -m agente_fiscal run`) maps to the same worker path.

---

## 7. Migration phases (strangler fig)

Order = edge first, center last. Each phase is independently shippable and reversible.

### Phase 0 — Inventory & baseline (0.5–1 day)
- [ ] Pin Python version (3.12) and export a real `backend/pyproject.toml` (uv) from current imports.
- [ ] Create `backend/pyproject.toml`, `backend/README.md`, `backend/.env.example`.
- [ ] Add a Dockerfile (multi-stage) + healthcheck.
- [x] Copy the archived legacy working tree → `backend/agente_fiscal/` as the working tree (done in Phase 0).
- [ ] Run existing tests to establish a green baseline.

### Phase 1 — Data layer: Postgres (3–5 days)
- [ ] Choose ORM: **SQLAlchemy 2.0 + Alembic** (recommended for a Python/FastAPI target).
- [ ] Implement schema from §4 with Alembic migrations.
- [ ] Write seed/migration scripts: Redis `tenant:*`/`conversation:*` → Postgres.
- [ ] Add a `clients` table; write a one-off script to load `clients.yaml`.
- [ ] `report_runs` + `generated_pdfs` tables (empty at first — schema ready before the pipeline uses them).
- [ ] Keep the Redis store **in read/write parallel** (dual-write) until the API reads SQL.

### Phase 2 — HTTP layer rewire (2–4 days)
- [ ] Rework `api/server.py` + routes: consume Clerk JWT → resolve `userId`/`tenantId` → scope queries.
- [ ] Remove the Python-side tenant/API-key store from production path; keep Redis only for rate limit + caches.
- [ ] Light endpoints only (`/health`, `/api/chat`, `/api/report` POST) — no heavy work in request handlers.
- [ ] Point `frontend/` to the new backend API (env `API_BASE_URL`).

### Phase 3 — Async pipeline (4–7 days)
- [ ] Add queue (RQ or Redis Streams) + worker process.
- [ ] Refactor `PipelineService` into discrete jobs (padron → browser → pdf → email) with `report_runs` updates.
- [ ] `POST /api/report` enqueues; `GET /api/report/{runId}` returns progress/status.
- [ ] Wire frontend history UI to `report_runs` (progress + final state + green-check "done" state).
- [ ] Move PDF output to S3/R2; email references the stored object.

### Phase 4 — Hard integrations (as needed)
- [ ] `arca_ws.py`: move TA cache from in-memory singleton to Redis (already shared). Keep openssl subprocess or replace with `cryptography` signing.
- [ ] `browser/` Composio: keep as-is behind the queue; add retry/backoff; store run artifacts.
- [ ] `memory/`: decide Engram retention (keep local service or migrate to a managed memory store).
- [ ] MCP server: keep as optional process; document auth status (HTTP auth was removed — TODO).

### Phase 5 — Cutover & decommission
- [x] ~~Feature-flag / canary: route a tenant to the new backend while others stay on the old path.~~
      N/A — a direct cutover was done instead (legacy folder deleted outright, no parallel old backend to canary against).
- [x] Drain Redis business-data keys; verify no production reads. `tenant:apikey:*`/`tenant:app:*`/`tenant:plan:*`/`tenant:developer:*`
      are gone from the codebase (Postgres via `ports.api_keys`); `tenant:tenant:*` (the old `TenantStore`) removed in this pass —
      see next item. Only `tenant:{tid}:conv:*` (best-effort conversation cache) and rate-limit/JWKS keys remain in Redis, by design.
- [x] Remove old `api/store.py` tenant code paths. `TenantStore` and `/v1/admin/tenants` deleted — no frontend consumer, no tests.
      Replaced with `/v1/clients` (`ports/clients.py` + `adapters/db_clients.py`), Postgres-backed CRUD over the `clients` table.
- [x] Archive/delete the legacy backend folder after a full regression pass (done in cutover Phase 5).

---

## 8. Deployment (Vercel + Docker)

### Recommended split

| Piece | Where | Why |
|---|---|---|
| `frontend/` Next.js | **Vercel (serverless)** | Native fit, already there |
| `backend/` FastAPI (web) | **Container: Fly.io / Railway / Render** | Long-lived process, websockets/SSE, no cold-start pain |
| Worker (queue consumer) | Same container platform, separate service | Runs minute-long browser jobs |
| PostgreSQL | **Neon** (serverless + pooler) or Supabase | Pooler is mandatory for serverless-ish access |
| Redis | **Upstash** or provider-managed | Cache/rate-limit/queue |
| PDF storage | **Cloudflare R2 / AWS S3** | Cheap object storage |

### Why not backend on Vercel serverless?

- Browser tasks run **minutes** (Composio poll every 2s, timeout 300s) — breaks function limits.
- SOAP ARCA needs certificates on disk + openssl subprocess + 12h TA cache shared across instances.
- ReportLab PDF generation is heavy and synchronous.
- The pipeline is a long job, not a request.

### Dockerfile skeleton

```dockerfile
# backend/Dockerfile — multi-stage
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

FROM base AS deps
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM base AS runtime
COPY --from=deps /app/.venv /app/.venv
COPY . .
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "agente_fiscal.api.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

Two containers from the same image:
- **web**: `uvicorn ...` (light endpoints only)
- **worker**: `python -m agente_fiscal.worker` (queue consumer)

### Deployment checklist

- [ ] Secrets via provider env vars (`REDIS_URL`, `DATABASE_URL`, `COMPOSIO_API_KEY`, ARCA certs, `SMTP_*`, `CLERK_SECRET_KEY`, `CLERK_DOMAIN`) — **never baked into the image**.
- [ ] ARCA certs: mount via secret volume (Fly.io secrets / Railway secret files) — not in git.
- [ ] Alembic migrations run as a **release step** before new instances start (not at runtime, or with an advisory lock).
- [ ] `DATABASE_URL` through a pooler (Neon pooler / PgBouncer).
- [ ] Object storage: PDFs written to R2/S3, not to container disk.
- [ ] Healthcheck on `/health` for both processes.

---

## 9. Environment variables (target)

```
# Core
DATABASE_URL=postgres://...            # via pooler
REDIS_URL=redis://...                  # Upstash / managed

# Auth (existing — do not redefine)
CLERK_SECRET_KEY=...
CLERK_DOMAIN=...

# ARCA
ESTUDIO_CUIT=...
ESTUDIO_CLAVE_FISCAL=...
ARCA_PROXY_URL=...                     # only if WSL2 proxy is still needed
CERT_DIR=/run/secrets/arca-certs

# Browser
COMPOSIO_API_KEY=...

# Memory
MEMORY_ENGRAM_URL=...
MEMORY_REDIS_CACHE_URL=...

# Email (Resend — default sender for API/worker, adapters/resend_email.py)
RESEND_API_KEY=...
EMAIL_FROM=...

# SMTP (legacy — CLI batch mode only, via clients.yaml; not read by API/worker)
SMTP_HOST=...
SMTP_PORT=...
SMTP_USER=...
SMTP_PASS=...

# App
CORS_ORIGINS=...
API_BASE_URL=https://api.example.com
```

---

## 10. Testing strategy

- **Port existing tests** (the legacy `tests/` layout) into `backend/agente_fiscal/tests/` and keep them green per phase.
- **Gaps to fill** (currently uncovered): `arca_ws`, `pdf_generator`, `browser/composio`, `rules_engine`, `billing`.
  - `rules_engine` and `billing` are pure — write table-driven unit tests FIRST (cheap, high value).
  - `arca_ws` and `browser` → integration tests behind env flags, never in CI defaults.
- **New**: `report_runs` state machine tests (queued → running → done/failed), queue retry tests.
- CI (frontend/backend split): backend job runs `pytest`, frontend job runs `tsc` + `biome` (already green).

---

## 11. Risks & non-goals

### Risks
| Risk | Mitigation |
|---|---|
| SOAP ARCA certs/openssl breaks on the new host | Keep certs as secrets; validate WSAA early in Phase 4; fallback to `cryptography` |
| Browser tasks are minutes-long and flaky | Queue + retries + timeouts; never run in web request |
| Redis business data loss during migration | Dual-write + drain script + verify counts |
| Frontend contract drift (camelCase keys) | Keep the same response shapes the frontend already expects |
| Engram as a local dependency | Decide managed alternative or keep service; make it optional |

### Non-goals (for now)
- ❌ Moving to TypeScript/Node for the backend (decision: keep Python).
- ❌ Multi-service microservices — one backend service + worker is the target.
- ❌ Rebuilding auth/tenants — they exist in the monorepo already.
- ❌ Serverless execution of the pipeline — containers only.

---

## 12. Definition of done (per phase)

- Phase 0: `uv run pytest` green in the new location; Dockerfile builds.
- Phase 1: SQL is the source of truth for business data; Redis keys drained.
- Phase 2: frontend talks to the new API with tenant-scoped queries; old tenant store unused.
- Phase 3: `POST /api/report` returns immediately; worker completes runs; history UI shows real progress and final state.
- Phase 4: WSAA/browser/memory work behind the queue in the container environment.
- Phase 5: old backend folder archived; zero reads from legacy Redis business keys.

---

*Related:* `ARCHITECTURE-ROADMAP.md` (frontend backend-readiness) · `frontend/` UI already consumes Clerk auth + tenant context.
