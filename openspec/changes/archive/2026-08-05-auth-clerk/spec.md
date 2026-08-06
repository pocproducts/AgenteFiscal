# Specification: Auth Clerk & Folder Restructure (Clean & Hexagonal)

## Purpose

De-couple frontend from backend, separate authentication logic using Hexagonal Architecture on the backend, and Clean Architecture on the frontend. Migrate from NextAuth to Clerk, replacing custom login/register forms with Clerk's prebuilt components, and mapping Clerk Organizations to Tenants.

---

## Capability: Folder Restructure

The system MUST restructure the application directories into clear `frontend/` and `backend/` boundaries to enforce physical separation of concerns.

### Requirement: Frontend/Backend Directories
- **Backend Directory (`backend/`)**: Submodules for database, AI SDK, and artifacts MUST live here.
- **Frontend Directory (`frontend/`)**: Components, hooks, localization (i18n), and editor utils MUST live here.
- **Legacy Imports Redirection**: The compiler (`tsconfig.json`) MUST resolve legacy import aliases (e.g. `@/components/*`, `@/hooks/*`, `@/lib/db/*`) to their new physical paths to minimize code churn.

| GIVEN | WHEN | THEN |
|-------|------|------|
| Restructured directories | App compiles | Paths resolve dynamically to `backend/` or `frontend/` without breaking existing imports |

---

## Capability: Hexagonal Backend Auth (`backend/auth`)

The auth system on the backend MUST follow Hexagonal Architecture, exposing a Port (interface) to the domain, and implementing interchangeable Adapters (infrastructure).

### Requirement: Domain Entities & Port
- **Entities**: `AuthUser` and `Tenant` (Organization) interfaces.
- **AuthPort**: Interface (`backend/auth/domain/ports/auth.port.ts`) exposing:
  - `getUserByEmail(email: string): Promise<AuthUser | null>`
  - `getTenantById(tenantId: string): Promise<Tenant | null>`
  - `listTenantsForUser(userId: string): Promise<Tenant[]>`
  - `createTenant(userId: string, name: string): Promise<Tenant>`

### Requirement: Swappable Adapters
- **InMemoryAuthAdapter**: Implements `AuthPort` delegating to mock data query functions (`backend/db/queries.ts`).
- **ClerkAuthAdapter**: Implements `AuthPort` calling Clerk Backend SDK (`clerkClient`).
- **AuthFactory**: Dynamically instantiates the adapter based on the `AUTH_ADAPTER` environment variable (`clerk` or `in-memory`).

| GIVEN | WHEN | THEN |
|-------|------|------|
| `AUTH_ADAPTER=in-memory` | AuthPort called | System delegates to `backend/db/queries.ts` |
| `AUTH_ADAPTER=clerk` | AuthPort called | System delegates to Clerk Backend API |

---

## Capability: Clean Frontend Auth (`frontend/auth`)

The frontend authentication layer MUST expose a unified React Context that isolates the presentation components from the underlying SDK hooks.

### Requirement: AuthProvider & useAuth
- **AuthProvider**: React context provider (`frontend/auth/presentation/context/auth.context.tsx`) that wraps the application.
- **useAuth Hook**: Exposes status, user, tenant, isGuest, signIn, signOut, createTenant, switchTenant.
- **Legacy Prop Drill Removal**: UI pages and components MUST consume session data via `useAuth()`. The legacy user prop drilling MUST be removed.

---

## Capability: Clerk Integration

The system MUST replace NextAuth with Clerk for session management, authentication pages, and middleware protection.

### Requirement: ClerkProvider & Localization
- **ClerkProvider**: Replaces NextAuth's `SessionProvider` in the root layout.
- **Spanish Localization**: Configured with `<ClerkProvider localization={esES}>` to translate authentication UI.

### Requirement: Prebuilt Auth Pages
- `/login` page MUST render Clerk `<SignIn />`.
- `/register` page MUST render Clerk `<SignUp />`.
- Pages MUST use standard redirects (`NEXT_PUBLIC_CLERK_SIGN_IN_URL` / `NEXT_PUBLIC_CLERK_SIGN_UP_URL`).

### Requirement: Middleware (Proxy) Protection
- **Proxy Boundary**: `proxy.ts` (Next 16 middleware file) MUST utilize `clerkMiddleware` to secure routes.
- **Resource Protection**: `/chat` route group MUST require authentication. `/login`, `/register`, `/api/auth` (legacy/in-memory), and assets MUST remain public.

---

## Out of Scope
- Webhook sync for real-time Postgres DB (uses on-demand adapter calls instead).
- Guest/anonymous session support (dropped from UI).
- Real Database migrations (remains in-memory mock for now).
