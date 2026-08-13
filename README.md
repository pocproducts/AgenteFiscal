# Agente Fiscal

Plataforma SaaS para estudios contables argentinos: calendario de vencimientos ARCA (AFIP), asistente fiscal con chat, gestión de clientes por CUIT y pipeline de reportes con verificación de deuda, facilidades, registro e IIBB.

Monorepo con dos servicios separados:

| Carpeta | Servicio | Stack |
|---|---|---|
| [`frontend/`](frontend/) | UI + BFF | Next.js 16 (App Router, Turbopack), React 19, AI SDK 6, Clerk, Tailwind 4, shadcn/ui, SWR |
| [`backend/`](backend/) | API + worker | Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL (Neon), Redis, PyJWT |

---

## Arquitectura

```
                    ┌──────────────────────────────────────────────┐
  Browser ────────► │ frontend/ (Next.js — Vercel)                 │
                    │  · Clerk: login/registro, sesión, tenants     │
                    │  · proxy.ts: clerkMiddleware protege rutas    │
                    │  · BFF: auth() + getToken() → Bearer JWT      │
                    └───────────────┬──────────────────────────────┘
                                    │ HTTPS  Authorization: Bearer <JWT de Clerk>
                                    ▼
                    ┌──────────────────────────────────────────────┐
                    │ backend/ (FastAPI — contenedor)              │
                    │  · ClerkJWTExtractor verifica el token:      │
                    │    HS256 (dev, CLERK_SECRET_KEY)             │
                    │    RS256 (prod, JWKS de CLERK_DOMAIN,        │
                    │           cache en Redis jwks:clerk)         │
                    │  · Resuelve sub → users.clerk_user_id,       │
                    │    org → tenants.clerk_org_id → tenant/plan  │
                    └──────┬──────────────┬──────────────┬─────────┘
                           │              │              │
                           ▼              ▼              ▼
                      PostgreSQL       Redis        Object storage
                      (Neon)          · rate limit   (S3/R2 — PDFs)
                      · tenants       · JWKS cache
                      · users         · ARCA TA cache
                      · clients       · cola de jobs
                      · report_runs   (worker)
                      · billing_events
```

### Autenticación (Clerk)

Clerk es un proveedor de identidad externo (SaaS) — no se deploya ni en el frontend ni en el backend. Los dos se integran con él:

1. **Frontend**: `ClerkProvider` + `proxy.ts` (`clerkMiddleware`) manejan la sesión del browser (login/registro, cambio de tenant con Organizations). El server de Next actúa de **BFF**: nunca expone `CLERK_SECRET_KEY` al cliente, solo `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`.
2. **BFF → backend**: `frontend/lib/backend/client.ts` resuelve la sesión con `auth()` + `getToken()` y reenvía `Authorization: Bearer <JWT>` a la API.
3. **Backend**: `backend/agente_fiscal/api/middleware/clerk.py` **verifica el JWT por su cuenta** — no confía en el frontend:
   - **Dev**: HS256 contra `CLERK_SECRET_KEY`.
   - **Prod**: RS256 contra el JWKS de `https://{CLERK_DOMAIN}/.well-known/jwks.json`, con cache de 1h en Redis (`jwks:clerk`) y fallback en memoria.
   - Mapea `sub` → `users.clerk_user_id` y `org_id` → `tenants.clerk_org_id`, y scoping por `tenant_id`.

> El backend es la única autoridad sobre "quién puede hacer qué". Si mañana hay app mobile o clientes API, se autentican igual: JWT de Clerk verificado en el backend.

---

## Estructura del monorepo

```
├── frontend/                  # Next.js 16 (UI + BFF)
│   ├── app/
│   │   ├── (auth)/            # login, register, tenant
│   │   ├── (chat)/            # chat, agent-sessions, analytics, settings, remote-browser
│   │   ├── (landing)/         # landing pública
│   │   ├── api/               # rutas BFF (chat, history, uploads, backend/health)
│   │   └── ping/              # healthcheck para Playwright
│   ├── lib/backend/client.ts  # BFF: JWT de Clerk → backend
│   ├── lib/i18n/              # ES/EN (toggle por cookie optimus-lang)
│   ├── proxy.ts               # clerkMiddleware (Next 16: middleware → proxy.ts)
│   ├── tests/e2e/             # Playwright
│   └── playwright.config.ts
│
├── backend/                   # Python/FastAPI
│   ├── agente_fiscal/
│   │   ├── api/
│   │   │   ├── middleware/clerk.py   # ClerkJWTExtractor (verificación JWT)
│   │   │   ├── middleware/auth.py    # dependencia de auth + rate limit
│   │   │   └── routes/               # chat, report, report_runs, clients, calendar, extract, admin…
│   │   ├── domain/           # reglas de negocio (ARCA, IIBB, matching)
│   │   ├── ports/            # contratos hexagonales (api_keys, clients, pdf, email, browser…)
│   │   ├── adapters/         # implementaciones (DB, Resend, Composio, ReportLab)
│   │   ├── db/               # SQLAlchemy async + modelos (users, tenants, clients, report_runs)
│   │   ├── pipeline/         # pipeline fiscal: Padrón A5 → browser → PDF → email
│   │   ├── worker/           # consumidor de cola (jobs asíncronos)
│   │   ├── billing/          # planes y costos
│   │   ├── chat/             # detección de intención + respuestas en español
│   │   └── cli.py            # CLI batch (uv run python -m agente_fiscal)
│   ├── alembic/              # migraciones de base de datos
│   ├── pyproject.toml        # uv
│   └── .env.example
│
└── openspec/                 # especificaciones SDD (cambios planificados/archivados)
```

---

## Cómo correrlo localmente

### Frontend (puerto 3000)

```bash
pnpm install
cd frontend
# Crear .env.local con las variables listadas abajo (no existe .env.example en frontend/).
pnpm dev
```

Variables del frontend: `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `API_BASE_URL` (default `http://localhost:8000`).

> **Troubleshooting**: si la página recarga en loop, el cache de Turbopack (`frontend/.next`, hasta 6–7 GB) se corrompió. Parar el server, `rm -rf frontend/.next`, y `pnpm dev` de nuevo.

### Backend (puerto 8000)

```bash
cd backend
uv sync
cp .env.example .env            # completar DATABASE_URL, REDIS_URL, CLERK_*
uv run alembic upgrade head
uv run uvicorn agente_fiscal.api.server:app --reload
```

Workers/CLI:

```bash
uv run python -m agente_fiscal --help
uv run python -m agente_fiscal run --config clients.yaml
```

---

## Variables de entorno

**Frontend** (`frontend/.env.local`):

| Variable | Uso |
|---|---|
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clave pública de Clerk (cliente) |
| `CLERK_SECRET_KEY` | Secreto del server Next (BFF) |
| `API_BASE_URL` | URL del backend (default `http://localhost:8000`) |

**Backend** (`backend/.env`, ver [`backend/.env.example`](backend/.env.example)):

| Variable | Uso |
|---|---|
| `DATABASE_URL` / `DATABASE_URL_UNPOOLED` | Postgres (pooled para API, directa para Alembic) |
| `REDIS_URL` | Cache, rate limit, cola de jobs |
| `CLERK_SECRET_KEY` / `CLERK_DOMAIN` | Verificación de JWT (HS256 dev / JWKS prod) |
| `COMPOSIO_API_KEY` | Browser remoto (Composio) |
| `MEMORY_ENGRAM_URL` | Memoria por-CUIT (Engram, opcional) |
| `RESEND_API_KEY` / `EMAIL_FROM` | Email de reportes |
| `CORS_ORIGINS` | Orígenes permitidos |
| `ESTUDIO_CUIT` / `ESTUDIO_CLAVE_FISCAL` / `CERT_DIR` | Credenciales ARCA (WSAA) |

---

## Tests

| Suite | Comando | Qué cubre |
|---|---|---|
| Frontend E2E (Playwright) | `pnpm test` | Páginas de auth, flujos de UI |
| Frontend unit (Vitest) | `pnpm --filter agente-fiscal-frontend test:unit` | Utilidades y errores |
| Backend (pytest) | `cd backend && uv run pytest` | API, reglas, adapters |

Playwright levanta el dev server automáticamente (o reusa uno existente) y espera a que `/ping` responda.

---

## Documentación relacionada

- [`ARCHITECTURE-ROADMAP.md`](ARCHITECTURE-ROADMAP.md) — roadmap de la UI y backend-readiness
- [`BACKEND-MIGRATION.md`](BACKEND-MIGRATION.md) — plan de migración del backend (strangler fig)
- [`openspec/`](openspec/) — especificaciones y cambios SDD
