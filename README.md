# Agente Fiscal

Plataforma SaaS para estudios contables argentinos: calendario de vencimientos ARCA (AFIP), asistente fiscal con chat, gestión de clientes por CUIT y un pipeline de reportes fiscales (Padrón A5 → navegador → PDF → email) con aprobación humana.

Este README es la **documentación operativa** del repositorio: arquitectura, estructura de código, autenticación, integraciones, modelo de datos, despliegue, variables de entorno y gotchas. Está pensado para que un agente DevOps (o un nuevo dev) entienda el sistema completo sin leer cada módulo.

Monorepo con dos servicios separados:

| Carpeta | Servicio | Stack |
|---|---|---|
| [`frontend/`](frontend/) | UI + BFF (Backend-for-Frontend) | Next.js 16 (App Router, Turbopack), React 19, AI SDK 6, Clerk, Tailwind 4, shadcn/ui, SWR |
| [`backend/`](backend/) | API + worker | Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL (Neon), Redis, PyJWT |

---

## Arquitectura

```
                    ┌──────────────────────────────────────────────────────┐
  Browser ────────► │ frontend/ (Next.js — Vercel)                         │
                    │  · Clerk: login/registro, sesión, tenants (Orgs)      │
                    │  · proxy.ts: clerkMiddleware protege rutas            │
                    │  · BFF (app/(chat)/api/*): auth() + getToken()        │
                    │    → reenvía Authorization: Bearer <JWT de Clerk>     │
                    │  · SSE: consume /v1/chat/message/stream y re-emite   │
                    │    eventos de monitor de agente (live_url, steps)    │
                    └───────────────────────┬──────────────────────────────┘
                                            │ HTTPS  Authorization: Bearer <JWT>
                                            ▼
                    ┌──────────────────────────────────────────────────────┐
                    │ backend/ (FastAPI — contenedor :8000)                │
                    │  · AuthMiddleware: Bearer JWT (Clerk) O X-API-Key     │
                    │    (fa_*) resuelta contra Postgres                    │
                    │  · ClerkJWTExtractor: HS256 (dev) / RS256+JWKS (prod) │
                    │    cache JWKS en Redis (jwks:clerk)                   │
                    │  · TenantContextMiddleware: scoping por tenant_id     │
                    │  · RateLimitMiddleware: Redis + plan (rpm/rpd)        │
                    │  · Chat: ToolSpec registry (6 tools) + intent routing │
                    │    → browser (Browserbase/Composio) o motor deter-   │
                    │      minista (Padrón A5 / RulesEngine) + formatters   │
                    │  · Worker IN-PROCESS (lifespan): cola report_runs,    │
                    │    human-in-the-loop (waiting_approval)               │
                    └──────┬──────────────┬──────────────┬─────────────────┘
                           ▼              ▼              ▼
                      PostgreSQL        Redis         (opcional) Object/
                      (Neon)           · rate limit   Blob storage
                      · tenants        · JWKS cache    (frontend artifacts)
                      · users          · cola (best-   · Engram memory
                      · clients          effort)
                      · conversations
                      · report_runs
                      · generated_pdfs  (bytes en la DB)
                      · billing_*
```

**Principios de diseño (backend):** arquitectura hexagonal. `domain/` (reglas de negocio, sin I/O), `ports/` (interfaces), `adapters/` (implementaciones: DB, browser, email, ARCA, memory). La API y el worker son los únicos que tocan adapters. Esto aisla la lógica fiscal de los proveedores externos (Clerk, Browserbase, Resend, ARCA).

### Diagrama de arquitectura (Archify)

Generado con [Archify](https://github.com/tt-a1i/archify) a partir del código real del repo. El diagrama es un artefacto **HTML interactivo** (temas claro/oscuro, zoom, rutas, historias, export a SVG/PNG desde el menú).

- **[Abrir diagrama interactivo (HTML)](docs/architecture.agente-fiscal.html)**
- **[Fuente tipado JSON IR](docs/architecture.agente-fiscal.architecture.json)** — regenerar con el CLI de Archify:
  ```bash
  node archify/bin/archify.mjs render architecture \
    docs/architecture.agente-fiscal.architecture.json \
    docs/architecture.agente-fiscal.html --quality standard
  ```

> Para incrustar una imagen estática en otro lado, abrí el HTML y usá el menú **Export → SVG/PNG**. El SVG inline que genera Archify no es XML estricto (es un viewer HTML), por eso el entregable canonical es el `.html`, no un `.svg` embebido.

---

## Estructura del monorepo

```
├── dev.sh                      # Orquestador local: up/down/restart/status/logs/migrate/seed
├── package.json                # Raíz pnpm: scripts proxy al frontend
├── pnpm-workspace.yaml         # Paquetes: frontend, backend
├── vercel.json                 # { "framework": "nextjs" }
├── backend/
│   ├── Dockerfile              # Multi-stage, uvicorn --workers 2 (solo backend; NO hay compose)
│   ├── pyproject.toml          # uv; python >=3.12
│   ├── .env.example            # Plantilla de variables (64 líneas)
│   ├── agente_fiscal/
│   │   ├── api/
│   │   │   ├── server.py       # Entrada FastAPI (app v2.0.0), lifespan: Redis+PG+worker
│   │   │   ├── middleware/     # clerk.py, auth.py, tenant.py, rate_limit.py, metrics.py
│   │   │   └── routes/         # chat, conversations, clients, profiles, memory,
│   │   │                        #   report, report_runs, calendar, extract, admin, monitor, health
│   │   ├── domain/             # tool_spec, intent_router, response_builder, rules_engine,
│   │   │                        #   tiers (planes), models, matching, cuit, approvals
│   │   ├── ports/              # api_keys, arca, browser, browser_sessions, clients,
│   │   │                        #   email, memory, pdf, profiles, settings
│   │   ├── adapters/           # browser/ (composio,browserbase,mock,factory,task),
│   │   │                        #   arca_ws (WSAA+Padrón A5), pdf_generator (ReportLab),
│   │   │                        #   resend_email, memory/, db_* (persistencia)
│   │   ├── pipeline/           # service.py: propuesta (gather+PDF) → ejecución (side-effects)
│   │   ├── worker/             # runner.py: consumidor in-process (FOR UPDATE SKIP LOCKED)
│   │   ├── db/                 # SQLAlchemy async + models/ (core, business) + seed, conversation_repo
│   │   ├── billing/            # re-exporta domain/tiers
│   │   ├── mcp/                # Servidor MCP (stdio/http) que expone las tools fiscales
│   │   └── cli.py              # Typer CLI: run, report, deuda, discover, worker, validate…
│   └── alembic/                # 7 migraciones (latest 0006_generated_pdfs_bytes)
│
├── frontend/
│   ├── app/
│   │   ├── (auth)/             # login, register, tenant (widgets Clerk)
│   │   ├── (chat)/             # chat, agent-sessions, remote-browser, analytics, settings
│   │   │   └── api/            # BFF: chat (central), history, messages, mail, profiles…
│   │   ├── (landing)/          # landing pública
│   │   ├── api/                # backend/health, locale
│   │   └── ping/               # healthcheck (GET → pong)
│   ├── lib/
│   │   ├── backend/client.ts   # BFF: JWT de Clerk → backend (callBackend / callBackendStream)
│   │   ├── agent-window.ts     # 6 tool keys + matcher regex + window por tool
│   │   └── i18n/               # ES/EN (cookie optimus-lang)
│   ├── proxy.ts                # clerkMiddleware (Next 16 usa proxy.ts)
│   ├── next.config.ts          # Sentry, botid, Turbopack cache, IS_DEMO basePath
│   ├── playwright.config.ts    # E2E (Chrome, webServer /ping)
│   └── package.json            # agente-fiscal-frontend v3.1.0
│
├── openspec/                   # Especificaciones SDD (cambios planificados/archivados)
├── archivos md/               # Notas de planificación humanas (roadmaps)
├── .run/                       # Artefactos runtime de dev.sh (pid/logs/redis) — gitignored
└── .atl/                       # skill-registry (tooling de agentes, no es código app)
```

> **Código muerto a ignorar:** `backend/ai/` es un módulo TypeScript (providers/prompts) del template original de chatbot; NO lo importa el backend Python (solo un alias de Vitest lo toca). `dump.rdb` en la raíz es un Redis stray; `dev.sh` usa `.run/redis/dump.rdb`.

---

## Backend

### Entrada y middleware

`api/server.py` crea la app FastAPI (título "Agente Fiscal API v2.0.0"). En el **lifespan** se conecta Redis (tolerante a caída, loop de reconexión de 30s), el engine de Postgres, se cablean los ports hexagonales y se arranca el **worker in-process** (`start_worker`). Orden de middleware (exterior→interior): `CORS → Metrics → Tenant → Auth → RateLimit → routes`. Si un integration-flag falla al inicializar, se levanta `IntegrationDisabledError` → **HTTP 503 `INTEGRATION_DISABLED`**.

### Rutas (`api/routes/`)

| Archivo | Endpoints principales |
|---|---|
| `health.py` | `GET /v1/health` (extendido) |
| `chat.py` | `POST /v1/chat/message` (sync), `POST /v1/chat/message/stream` (SSE), `POST /v1/chat/wizard` (multi-turn SSE), `GET /v1/chat/reports/{filename}`, `POST /v1/chat/reports/send` |
| `conversations.py` | `POST/GET /v1/conversations`, `GET/DELETE /v1/conversations/{id}` |
| `clients.py` | CRUD de clientes por CUIT (`POST/GET`, `GET/PATCH/DELETE /v1/clients/{id}`) |
| `profiles.py` | Identidad del tenant para reportes (`POST/GET`, `GET/PATCH/DELETE /v1/profiles/{id}`) |
| `memory.py` | Memoria fiscal Engram (`GET /v1/memory/{cuit}`, `POST /v1/memory/observe`) |
| `report.py` | `GET /v1/taxpayer/{cuit}`, `POST /v1/report` (pipeline legacy) |
| `report_runs.py` | `POST /v1/report-runs` (enqueue), `GET /v1/report-runs/{id}`, `…/approve`, `…/reject` (human-in-the-loop) |
| `calendar.py` | `POST /v1/calendar` |
| `extract.py` | `POST /v1/extract` (extracción browser) |
| `admin.py` | Self-service de developers/apps/API-keys (`/v1/admin/register`, `/v1/admin/apps`, `/v1/admin/keys`, `/v1/admin/api-keys/...`) |
| `monitor.py` | `GET /v1/system/features`, `/v1/system/metrics`, `/v1/system/services`, `/v1/system/activity`, `/v1/system/errors` |

### Chat: ToolSpec registry + intent routing

El registry declarativo vive en `domain/tool_spec.py`:

- `ToolSpec` (dataclass frozen): `tool_key`, `intent`, `keywords`, `task_flags`, `formatter_name`, `needs_browser`, `tool_name`.
- `TOOL_SPECS`: **6 tool keys**; `INTENT_TO_KEY` es una biyección Intent→key.

**Las 6 herramientas fiscales:**

| tool_key | Intent | needs_browser | Fuente de datos | Formatter |
|---|---|---|---|---|
| `sistemaregistral` | `SISTEMA_REGISTRAL` | sí | Browserbase/Composio | `format_registro_response` |
| `deudavencimientos` | `DEUDA_VENCIMIENTOS` | sí | browser | `format_deuda_response` |
| `misfacilidades` | `MIS_FACILIDADES` | sí | browser | `format_facilidades_response` |
| `rentascordoba` | `RENTAS_CORDOBA` | sí | browser (IIBB Córdoba) | `format_rentas_response` |
| `consultaarca` | `CONSULTA_ARCA` | no | Padrón A5 (determinista) | `format_consultaarca_response` |
| `calendariovencimientosarca` | `CALENDARIO_VENCIMIENTOS_ARCA` | no | RulesEngine (determinista) | `format_calendario_response` |

Además, `informefiscal` (macro = todas las tools de datos) y `enviarmail` (envío) se manejan en el dispatch pero no son filas ToolSpec.

**Routing de intención** (`domain/intent_router.py`): regex sobre el mensaje + extracción de CUIT; prioridad deuda→calendario→facilidades→rentas→consultaarca; `reporte` (pipeline completo) es el agregador; desconocido → ayuda.

**Dispatch** (en `chat.py`): `_handle_tool_data` ramifica a `_run_browser_tool` (si `needs_browser`, llama `build_browser_tasks(**task_flags)` → `BrowserPort.run_single`, streamea `live_url`/`agent_step`) o `_run_engine_tool` (determinista: Padrón A5 / RulesEngine). Consolidado en `_handle_selected_tools_pipeline`. Los **formatters** producen markdown por tool en `domain/response_builder.py`.

**Contrato SSE** (`/v1/chat/message/stream`, `/v1/chat/wizard`): `conversation_start` → `progress*` → (`live_url`, `agent_step`, `task_update` para tools browser) → `complete` (con `reply`, `data`, `conversation_id`, `pipeline_steps`, opcional `pdf_url`, `report_run_id`). Usa `asyncio.Queue` + `asyncio.to_thread` para el pipeline bloqueante.

### Browser multi-backend (`adapters/browser/`)

Registro de providers en `provider.py` (`PROVIDERS`: `composio`, `browserbase`, `mock`), seleccionado por `BROWSER_PROVIDER`. `browserbase.py` (Agents API, contexto persistente), `composio.py`, `mock.py` (local determinista), `factory.py` (`build_browser_tasks`), `task.py` (BrowserTask y subtasks), `iibb_router.py`, `workflows/`.

**Sesiones persistentes:** la tabla `browser_sessions` guarda el contexto del provider por (tenant, profile); se adquiere/libra con `FOR UPDATE SKIP LOCKED` (TTL configurable). Esto permite reusar la sesión del navegador entre ejecuciones.

### Pipeline y Worker

`pipeline/service.py` implementa un flujo de **dos fases**:
1. **Propuesta** (`run_proposal`): junta datos (Padrón A5 → RulesEngine → extracción browser opcional) y genera el PDF (ReportLab). No aplica side-effects.
2. **Ejecución** (`execute_actions`): corre solo las acciones aprobadas (ej. enviar email).

`worker/runner.py` es un runner async **in-process** (arrancado por el lifespan de FastAPI). `ReportRunner.claim_next_queued` usa `SELECT … FOR UPDATE SKIP LOCKED` para reclamo atómico (seguro bajo Docker `--workers 2`). Estados: `queued → running → done/failed/waiting_approval`. Acciones de riesgo pendientes parkan en `waiting_approval`; el admin aprueba y se re-encola para ejecutar solo lo aprobado. Tras `done`, persiste los bytes del PDF en Postgres.

### Modelo de datos (SQLAlchemy async + Alembic)

`db/models/`:
- **core.py:** `Tenant`, `User`, `TenantMember`, `ApiKey` (hash sha256 de `key_hash`, nunca plaintext), `App`, `Plan`, `PlanPrice`, `Subscription`.
- **business.py:** `Conversation`, `Message`, `Client` (tenant+CUIT), `Profile` (identidad tenant, gate para reportes), `BrowserSession` (contexto provider persistido), `ReportRun` (estado `queued/running/done/failed/waiting_approval`, `pending_actions`, `approved_by`), `GeneratedPdf` (LargeBinary `content_bytes` — **en Postgres**, no S3/R2), `BillingEvent`, `TokenPackage`, `TokenBalance`, `TokenTransaction`, `Invoice`, `Payment`.

**Postgres es la fuente de verdad.** Redis solo cachea rate-limit, JWKS y conversaciones best-effort. Si Redis cae, el backend arranca degradado (el rate-limit pasa a pass-through, auth/Clerk siguen funcionando).

> Esquema completo de columnas, FKs y enums: [Modelado de datos (PostgreSQL)](#modelado-de-datos-postgresql).

### Billing, MCP y CLI

- `billing/`/`domain/tiers.py`: planes `free` (50 contrib, flat $99), `pro` (10, $0.05/s browser), `pro_max` (200, $199), `enterprise` (unlimited, $299). Las tablas de suscripción/pago existen pero **no hay Stripe/MercadoPago cableado** en el código.
- `mcp/`: servidor MCP (stdio o HTTP vía `MCP_TRANSPORT`/`MCP_PORT`) que expone las tools fiscales.
- `cli.py` (Typer): `validate`, `generate-template`, `discover`, `run` (pipeline completo sobre `clients.yaml`), `deuda`, `report` (interactivo), `worker` (loop standalone).

---

## Modelado de datos (PostgreSQL)

El backend usa SQLAlchemy 2 async + Alembic. **18 tablas** en dos módulos (`db/models/core.py`, `db/models/business.py`). Todas heredan `UuidPkMixin` (`id` UUIDv7, PK) y `TimestampMixin` (`created_at`/`updated_at` TIMESTAMPTZ con `server_default=now()`), salvo `messages` (solo `created_at`). La cadena de migraciones es lineal y su head actual es **`0006`** (`generated_pdfs.content_bytes`). Postgres es la fuente de verdad; Redis solo cachea.

### Dominio core — identidad, tenants, auth y planes

**`tenants`** — organización del cliente (Clerk Org). `clerk_org_id` (varchar(255), único, nullable hasta vincular).

| Columna | Tipo | Nul | Clave | Notas |
|---|---|---|---|---|
| `name` | varchar(255) | NO | | |
| `clerk_org_id` | varchar(255) | SÍ | única | `tenants.clerk_org_id` |

**`users`** — persona (Clerk user). `clerk_user_id` (varchar(255), único), `email` (varchar(320)), `display_name`.

**`tenant_members`** — membresías. (`tenant_id`,`user_id`) único; `role` ∈ {owner,admin,member} (check); FKs a `tenants`/`users` CASCADE.

**`api_keys`** — API keys server-to-server (prefijo `fa_`). `key_hash` = **sha256 hex (64 chars)** del raw key (el plaintext nunca se persiste); `scopes` (text[]), `expires_at`, `is_active`, `last_used_at`, `revoked_at`. Única en `key_hash`.

**`apps`** — apps registradas por developer. `tenant_id`→tenants, `developer_id`→users (SET NULL).

**`plans`** — catálogo global (no por tenant). `slug` único, `tier` ∈ {free,pro,pro_max,enterprise}, `currency` ∈ {ARS,USD}, `tokens_included`, `limits`/`features` (JSONB). Sembrado en `a3183d34be98`.

**`plan_prices`** — (`plan_id`,`period`) único; `period` ∈ {monthly,yearly}; `price_cents`.

**`subscriptions`** — una activa por tenant (índice parcial único sobre `tenant_id` donde status activo). `plan_id`→plans (RESTRICT), `status` ∈ {trialing,active,past_due,canceled,expired}, `provider` ∈ {stripe,mercadopago,manual}.

### Dominio business — chat, clientes, reportes, navegador

**`conversations`** — historial de chat. `tenant_id`, `user_id`→users (SET NULL), `profile_id`→profiles (SET NULL, desde 0004), `title`, `status` ∈ {running,done}.

**`messages`** — `conversation_id`→conversations (CASCADE), `role` ∈ {system,user,assistant,tool}, `parts` (JSONB). *No tiene `updated_at`.*

**`clients`** — contribuyentes por CUIT. (`tenant_id`,`cuit`) único; `name`, `email`, `config` (JSONB).

**`profiles`** (0004) — identidad del tenant para reportes (gate). (`tenant_id`,`cuit`) único; `status` ∈ {active,inactive}; `created_by`→users.

**`browser_sessions`** (0005) — contexto de navegador persistido. (`tenant_id`,`profile_id`,`provider`) único; `provider` (default `browserbase`, sin check), `context_id`, `status` ∈ {active,in_use}, métricas `proxy_bytes`/`duration_ms`/`cost_cents`, `expires_at`.

**`report_runs`** — ejecuciones del pipeline fiscal. `profile_id`→profiles (RESTRICT, NOT NULL), `client_id`→clients (SET NULL, FK compuesta `(client_id,tenant_id)`), `cuit`, `status` ∈ {queued,running,done,failed,waiting_approval} (ampliado en 0003), `steps`/`result_summary`/`error` (JSONB), `period_year`/`period_month` (0004), `pending_actions` (JSONB, 0003), `approved_by`/`approved_at`/`rejection_reason` (0003).

**`generated_pdfs`** — PDFs generados. `report_run_id`→report_runs (CASCADE), `storage_key`, `filename`, `size_bytes`, **`content_bytes`** (BYTEA — PDF en Postgres, 0006).

### Dominio billing / tokens

**`billing_events`** — ledger de facturación. `tenant_id`, `plan_id`→plans (SET NULL), `description`, `amount`, `currency` ∈ {ARS,USD}.

**`token_packages`** — paquetes de tokens. `name`, `tokens` (>0), `price_cents`.

**`token_balances`** — saldo por tenant (una fila, `tenant_id` único), `balance`.

**`token_transactions`** — ledger append-only firmado. `tenant_id`, `user_id`/`profile_id`→users/profiles (SET NULL), `type` ∈ {purchase,grant,consume,refund,expiry}, `delta`, `balance_after`, `reference_type`/`reference_id`.

**`invoices`** — `subscription_id`→subscriptions (SET NULL), `kind` ∈ {subscription,recharge}, `status` ∈ {draft,open,paid,void,refunded}, `provider` ∈ {stripe,mercadopago,manual}, `metadata` (JSONB).

**`payments`** — `invoice_id`→invoices (CASCADE), `provider`, `status` ∈ {pending,succeeded,failed,refunded}, `amount`.

### Relaciones (grafo FK / ERD)

- `tenants` es raíz: `tenant_members`, `api_keys`, `apps`, `clients`, `conversations`, `profiles`, `browser_sessions`, `report_runs`, `billing_events`, `token_balances`, `token_transactions`, `invoices`, `subscriptions` → `tenants.id` (CASCADE).
- `users` → `tenant_members`, `apps.developer_id` (SET NULL), `conversations.user_id`, `profiles.created_by`, `report_runs.user_id`, `token_transactions.user_id` (SET NULL).
- `profiles` → `conversations.profile_id`, `report_runs.profile_id` (RESTRICT), `token_transactions.profile_id`, `browser_sessions.profile_id` (SET NULL).
- `clients` → `report_runs.client_id` (SET NULL) + FK compuesta `report_runs(client_id,tenant_id)`.
- `plans` → `plan_prices.plan_id` (CASCADE), `subscriptions.plan_id` (RESTRICT), `billing_events.plan_id` (SET NULL).
- `conversations` → `messages.conversation_id` (CASCADE).
- `report_runs` → `generated_pdfs.report_run_id` (CASCADE).
- `subscriptions` → `invoices.subscription_id` (SET NULL).
- `invoices` → `payments.invoice_id` (CASCADE).

### Dominios de valor (enums / check constraints)

`tenant_members.role` {owner,admin,member} · `plans.tier` {free,pro,pro_max,enterprise} · `subscriptions.status` {trialing,active,past_due,canceled,expired} · `conversations.status` {running,done} · `messages.role` {system,user,assistant,tool} · `profiles.status` {active,inactive} · `browser_sessions.status` {active,in_use} · `report_runs.status` {queued,running,done,failed,waiting_approval} · `token_transactions.type` {purchase,grant,consume,refund,expiry} · `invoices.kind` {subscription,recharge} / `invoices.status` {draft,open,paid,void,refunded} · `payments.status` {pending,succeeded,failed,refunded}. `browser_sessions.provider` no tiene check (solo `browserbase` sembrado).

### Notas de flujo de datos

- **Historial de chat:** `Conversation` → `Message` (role + `parts` JSONB), 1:N, cascade.
- **PDFs en Postgres:** `GeneratedPdf.content_bytes` (BYTEA) guarda el binario; `storage_key` es la referencia a object storage (no usado hoy).
- **Sesiones de navegador:** `BrowserSession` persiste el `context_id` de Browserbase por (tenant, profile); `status` cicla active↔in_use; métricas al liberar.
- **API keys:** `key_hash` es sha256 del raw — el plaintext nunca se persiste.
- **Human-in-the-loop:** `ReportRun.pending_actions` + `approved_by`/`approved_at`; estado `waiting_approval` (0003).
- **Billing/tokens:** `subscriptions` → `invoices` → `payments`; `token_balances` mutado por `token_transactions` append-only.

---

## Frontend

### Stack (verificado en `package.json`)

Next.js **16.2.12** (App Router, Turbopack), React 19, TypeScript 5.6, Tailwind v4, shadcn/Radix, SWR 2.2, **Vercel AI SDK 6**, Clerk 6.39, Sentry 10, Playwright 1.50 (E2E), Vitest 4 (unit), Biome/ultracite. Packages de raíz y `agente-fiscal-frontend`.

### Estructura y BFF

- `app/(chat)/api/chat/route.ts` es el **BFF central**. Usa `createUIMessageStream`/`createUIMessageStreamResponse`.
  - Si detecta un tool key (vía `lib/agent-window.ts`) o `informefiscal` → abre el monitor de agente de forma optimista (`data-agent-session-start` con `toolName`/`toolKey`/`windowMs`/`profileId`), llama `/v1/chat/message/stream` (SSE), y re-emite `data-agent-session-liveurl`, `data-agent-browser-step`, `data-agent-task-update`, luego el markdown como `text-delta`s, y `data-agent-session-complete`. La ventana queda abierta `windowMs` tras el comando.
  - Si es mensaje no-tool / motor determinista → `callBackend("/v1/chat/message")` y hace stream del reply como deltas de texto.
- `lib/backend/client.ts`: cliente BFF (server-only). `callBackend`/`callBackendStream` reenvían el JWT de la sesión Clerk como `Authorization: Bearer` a `API_BASE_URL` (default `http://localhost:8000`). Nunca se importa desde componentes cliente.
- `lib/agent-window.ts`: única fuente de verdad de los 6 `tool_key`s, matchers regex, `TOOL_NAMES`, `TOOL_WINDOW_OVERRIDES` (ventana por tool en ms), `NO_MONITOR_TOOLS` (motores deterministas), `AGENT_SESSION_WINDOW_MS`.
- `lib/i18n/`: ES/EN, locale en cookie `optimus-lang`, default ES.

### Middleware y despliegue

- `proxy.ts` (forma `proxy.ts` de Next 16): `clerkMiddleware` que redirige a `/login` en rutas chat/agent-sessions/analytics/settings/remote-browser si no hay sesión. Matcher cubre todo salvo internos/estáticos de Next.
- `next.config.ts`: Sentry (`withSentryConfig`), botid, `cacheComponents`, `reactCompiler`, `IS_DEMO` (basePath `/demo`), Turbopack FS dev cache, patrones de blob.
- `instrumentation.ts` + `sentry.{client,server,edge}.config.ts`.

---

## Autenticación y multi-tenancy

Clerk es un proveedor de identidad externo (SaaS) — no se deploya. Los dos servicios se integran con él:

1. **Frontend:** `ClerkProvider` + `proxy.ts` manejan la sesión del browser (login/registro, cambio de tenant con Organizations). El server de Next actúa de **BFF**: nunca expone `CLERK_SECRET_KEY` al cliente, solo `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`.
2. **BFF → backend:** `lib/backend/client.ts` resuelve la sesión con `auth()` + `getToken()` y reenvía `Authorization: Bearer <JWT>`.
3. **Backend:** `api/middleware/clerk.py` **verifica el JWT por su cuenta** — no confía en el frontend:
   - **Dev:** HS256 contra `CLERK_SECRET_KEY`.
   - **Prod:** RS256 contra el JWKS de `https://{CLERK_DOMAIN}/.well-known/jwks.json`, con cache de 1h en Redis (`jwks:clerk`) y fallback en memoria.
   - Mapea `sub` → `users.clerk_user_id` y `org_id` → `tenants.clerk_org_id`, y scoping por `tenant_id`.

**Doble vía de auth:** además del JWT de Clerk, los requests con header `X-API-Key` prefijado `fa_` se resuelven contra `ApiKeyPort` (Postgres) → tenant/app/developer/plan + scopes + `rate_limit_config`. Útil para integraciones server-to-server y el servidor MCP.

> El backend es la única autoridad sobre "quién puede hacer qué". Si mañana hay app mobile o clientes API, se autentican igual: JWT de Clerk (o API key) verificado en el backend.

---

## Integraciones y feature flags

Todas las integraciones externas están detrás de flags (en `config.py` / `.env`). **Por defecto están APAGADAS y devuelven 503 `INTEGRATION_DISABLED`** si se invocan sin habilitar. Esto es clave para el despliegue: el smoke test en prod debe prender los flags correctos.

| Flag | Default | Qué habilita |
|---|---|---|
| `ARCA_ENABLED` | `false` | WSAA + Padrón A5 (SOAP/TA, `consultaarca`, `consultaarca` tool) |
| `BROWSER_ENABLED` | `false` | Provider de navegador (deuda, facilidades, registral, rentas) |
| `BROWSER_PROVIDER` | `browserbase` | `browserbase` \| `composio` \| `mock` |
| `BROWSER_SESSION_TTL_SECONDS` | `3600` | TTL de sesiones persistentes |
| `BROWSER_SESSION_REUSE` | `true` | Reusar contexto entre ejecuciones |
| `PDF_ENABLED` | `true` | Generación de PDF (ReportLab) |
| `MEMORY_ENABLED` | `true` | Memoria fiscal Engram (`MEMORY_*`) |

El endpoint `GET /v1/system/features` refleja el estado en vivo de estos flags.

---

## Cómo correrlo localmente

### Recomendado: `dev.sh` (orquesta todo, no necesita compose)

```bash
./dev.sh up [--migrate]     # Redis + backend (:8000, uvicorn, worker in-process) + frontend (:3000)
./dev.sh status             # estado + health de los tres servicios
./dev.sh logs [backend|frontend]
./dev.sh migrate            # alembic upgrade head
./dev.sh seed               # seed idempotente (tenants/plans iniciales)
./dev.sh down / restart [--migrate]
./dev.sh help
```

`dev.sh` **levanta Redis local como daemon** (puerto 6379) solo si no hay uno respondiendo; su dump vive en `.run/redis/` (gitignored). El worker fiscal corre **in-process dentro de uvicorn**, así que `up` ya lo inicia. Requisitos: `backend/.venv` (con `uvicorn`/`alembic`), `pnpm`, `redis-server`, `backend/.env`, `frontend/.env.local`. Si falta Redis, el backend arranca degradado.

### Manual (sin dev.sh)

**Backend** (prepara el venv con uv):
```bash
cd backend
uv sync                       # crea .venv
cp .env.example .env          # completar DATABASE_URL, REDIS_URL, CLERK_*, flags
uv run alembic upgrade head
uv run uvicorn agente_fiscal.api.server:app --reload
```
CLI / worker standalone:
```bash
uv run python -m agente_fiscal --help
uv run python -m agente_fiscal run --config clients.yaml
uv run python -m agente_fiscal worker
```

**Frontend:**
```bash
pnpm install
cd frontend
# Crear .env.local con NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, CLERK_SECRET_KEY, API_BASE_URL
pnpm dev
```

> **Troubleshooting Turbopack:** si la página recarga en loop, el cache de Turbopack (`frontend/.next`, puede crecer 6–7 GB) se corrompió. Parar el server, `rm -rf frontend/.next`, y `pnpm dev` de nuevo.

---

## Variables de entorno

**Frontend** (`frontend/.env.local` — no hay `.env.example` en frontend/):

| Variable | Uso |
|---|---|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clave pública de Clerk (cliente) |
| `CLERK_SECRET_KEY` | Secreto del server Next (BFF) |
| `API_BASE_URL` | URL del backend (default `http://localhost:8000`) |
| `NEXT_PUBLIC_SENTRY_DSN`, `SENTRY_ORG`, `SENTRY_PROJECT`, `SENTRY_AUTH_TOKEN` | Sentry |
| `IS_DEMO` | Habilita basePath `/demo` |
| `E2E_CLERK_USER_EMAIL` / `E2E_CLERK_USER_PASSWORD` | Setup de Playwright (si falta, los tests se saltean) |

**Backend** (`backend/.env`, plantilla en [`backend/.env.example`](backend/.env.example)):

| Variable | Default | Uso |
|---|---|---|
| `DATABASE_URL` / `DATABASE_URL_UNPOOLED` | `''` | Postgres (pooled para API, directa para Alembic) |
| `REDIS_URL` | `redis://localhost:6379/0` | Cache, rate limit, cola |
| `MEMORY_REDIS_CACHE_URL` | `redis://localhost:6379/0` | Cache de memoria Engram |
| `MEMORY_REDIS_MAX_MB` | `25` | Tope de cache |
| `CLERK_SECRET_KEY` / `CLERK_DOMAIN` | `''` | Verificación JWT (HS256 dev / JWKS prod) |
| `CORS_ORIGINS` | `http://localhost:3000,3001` | Orígenes permitidos (comma-separated) |
| `RESEND_API_KEY` / `EMAIL_FROM` | `''` | Email de reportes |
| `COMPOSIO_API_KEY` | `''` | Browser remoto (Composio) |
| `BROWSERBASE_API_KEY` / `BROWSERBASE_PROJECT_ID` | `''` | Browserbase |
| `ESTUDIO_CUIT` / `ESTUDIO_CLAVE_FISCAL` | `20324837796` / `''` | Credenciales ARCA (WSAA) |
| `CERT_DIR` | `.certificados-arca` | Certs ARCA (`produccion.crt`/`produccion.key`) — gitignored |
| `ARCA_PROXY_URL` | — | Proxy opcional para WSAA |
| `SENTRY_DSN` / `APP_ENV` | `''` / `development` | Telemetría |
| `MCP_TRANSPORT` / `MCP_PORT` | `stdio` / `8000` | Servidor MCP |
| `ARCA_ENABLED` | `false` | WSAA/Padrón A5 |
| `BROWSER_ENABLED` / `BROWSER_PROVIDER` | `false` / `browserbase` | Navegador |
| `BROWSER_SESSION_TTL_SECONDS` / `BROWSER_SESSION_REUSE` | `3600` / `true` | Sesiones browser |
| `PDF_ENABLED` | `true` | Generación de PDF |
| `MEMORY_ENABLED` | `true` | Memoria Engram |

---

## Despliegue

- **Backend:** `backend/Dockerfile` (multi-stage, `uvicorn … --workers 2`). **No hay `docker-compose.yml`** en el repo; el orquestado local es `dev.sh`. El worker corre in-process, así que un solo contenedor ya ejecuta API + worker. El reclamo `FOR UPDATE SKIP LOCKED` permite escalar a 2+ workers sin doble ejecución.
- **Frontend:** Vercel (framework Next.js, ver `vercel.json`). Requiere `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` y `API_BASE_URL` apuntando al backend deployado.
- **Postgres:** Neon (pooled `DATABASE_URL` + unpooled `DATABASE_URL_UNPOOLED` para Alembic). Async SQLAlchemy.
- **Redis:** requerido para rate-limit/JWKS/cache. Opcional en el arranque (degrada), pero **necesario en prod** para el comportamiento correcto de auth/rate-limit.
- **PDFs:** se guardan como `content_bytes` en Postgres (`generated_pdfs`). No se usa object storage externo hoy (aunque `@vercel/blob` existe en el frontend para artifacts de UI).
- **Flags en prod:** prender `ARCA_ENABLED`, `BROWSER_ENABLED` y los proveedor keys según corresponda; de lo contrario esos endpoints devuelven 503.
- **CORS:** actualizar `CORS_ORIGINS` con los dominios deployados (default localhost).
- **TLS/Ingress:** el SSE de `/v1/chat/message/stream` es de larga duración (el BFF usa timeout de 600s) — el proxy/ingress debe permitir conexiones SSE largas.

---

## Tests

| Suite | Comando | Qué cubre |
|---|---|---|
| Frontend E2E (Playwright) | `pnpm test` (o `pnpm --filter agente-fiscal-frontend test`) | Auth, flujos de UI; levanta dev server, espera `/ping`. Se saltea si faltan creds E2E de Clerk. |
| Frontend unit (Vitest) | `pnpm test:unit` (`vitest run`) | `lib/*.test.ts` (agent-window, cuit, errors, utils). Alias `@/lib/ai → ../backend/ai`. |
| Backend (pytest) | `cd backend && uv run pytest` | API, reglas, adapters, tool_spec, intent_router, rules_engine, aislamiento multitenant, api_keys/clients, browser provider, report runner/approval, features, arca_ws, db_browser_sessions. Usa `fakeredis` + Postgres de test. |

---

## Observabilidad

- **Sentry:** cableado en web (`withSentryConfig`, `instrumentation.ts`) y Python (`telemetry.py`, init en server + worker). Necesita `SENTRY_*` / `NEXT_PUBLIC_SENTRY_DSN` o corre silencioso.
- **Endpoints de sistema** (`monitor.py`): `GET /v1/system/features` (estado de flags), `/v1/system/metrics`, `/v1/system/services`, `/v1/system/activity`, `/v1/system/errors`.
- **Health:** backend `GET /v1/health`; frontend `GET /ping` (usado por `dev.sh` y Playwright).

---

## Gotchas operacionales (léelo antes de deployar)

1. **Redis es best-effort, no fuente de verdad.** Postgres tiene tenants/clients/plans/API keys/conversaciones/PDFs. Redis = rate-limit + JWKS + cache. Si cae, el backend arranca degradado. `dump.rdb` en la raíz es un stray; `dev.sh` usa `.run/redis/dump.rdb`.
2. **Integraciones default OFF.** `ARCA_ENABLED=false`, `BROWSER_ENABLED=false`, `PDF_ENABLED=true`. Invocarlas apagadas → **503 `INTEGRATION_DISABLED`**. El deploy de prod debe prenderlas.
3. **PDFs en Postgres, no S3/R2.** `GeneratedPdf.content_bytes` es LargeBinary. El docstring original decía S3/R2 pero hoy están en la DB. Clarificar antes de agregar R2.
4. **Clerk HS256/RS256 blur.** `clerk.py` cae a HS256 (dev `CLERK_SECRET_KEY`) incluso en la ruta RS256/JWKS. En prod asegurar `CLERK_DOMAIN` + tipo de clave correcto; un mismatch dev/prod aceptará HS256 silenciosamente.
5. **CORS** con `allow_credentials=True` — actualizar `CORS_ORIGINS` para dominios deployados.
6. **Worker in-process** en el lifespan de uvicorn. `dev.sh up` ya lo arranca. Bajo Docker `--workers 2`, el reclamo `FOR UPDATE SKIP LOCKED` previene doble ejecución (se agregó tras un bug real de doble corrida).
7. **SSE de larga duración** en `/v1/chat/message/stream` — el ingress/proxy debe permitir conexiones largas (timeout 600s en el BFF).
8. **Rate limit** Redis-backed y por plan (rpm/rpd). Sin Redis → pass-through (sin límite), no crashea.
9. **`backend/ai/` es código muerto** (TS del template original); ignorarlo.
10. **`use-remote-browsers` aún no tiene fetcher al backend** — la tabla remote-browser renderiza esqueleto/vacío (TODO frontend).
11. **`.certificados-arca/` y `storage/` son gitignored** — provisionar certs ARCA out-of-band; el pipeline lee `CERT_DIR`.
12. **Certificados ARCA** requieren `ESTUDIO_CUIT` + `ESTUDIO_CLAVE_FISCAL` + `CERT_DIR` con `produccion.crt`/`produccion.key` para que `ARCA_ENABLED` funcione de verdad.

---

## Documentación relacionada

- [`archivos md/ARCHITECTURE-ROADMAP.md`](archivos%20md/ARCHITECTURE-ROADMAP.md) — roadmap de UI y backend-readiness
- [`archivos md/BACKEND-MIGRATION.md`](archivos%20md/BACKEND-MIGRATION.md) — plan de migración del backend (strangler fig)
- [`openspec/`](openspec/) — especificaciones y cambios SDD
- [`backend/.env.example`](backend/.env.example) — plantilla de variables del backend
- [`dev.sh`](dev.sh) — comentarios de cabecera con toda la superficie de comandos
