# Specification: Auth + Tenant (clean architecture for mock-now / Clerk-later)

## Purpose

Put auth and tenant behind a port/adapter boundary so the UI works fluidly TODAY against the in-memory mock and can swap to Clerk/real backend later without touching UI code. UI consumes only `useAuth()`; adapters are interchangeable.

## Capability: auth-core

### Requirement: Register/Login over the in-memory adapter

The system MUST allow registration and login with any valid email and password of at least 6 characters, backed by the in-memory auth adapter. Registration with an existing email MUST return a clear `user_exists` error; login with a wrong password MUST return an auth error; passwords under 6 characters MUST be rejected by the existing zod validation.

| Scenario | GIVEN | WHEN | THEN |
|----------|-------|------|-------|
| Valid login | A user registered with email+password | They submit the same credentials at login | Status is `authenticated` and a session is started |
| Existing email | A user with email `a@b.com` exists | Register form submits `a@b.com` again | Clear `user_exists` error surfaces to the UI |
| Wrong password | A user exists | Login submits an incorrect password | Auth error surfaces (invalid credentials), no session |
| Short password | Register form filled | Password has fewer than 6 characters | Zod validation rejects the submission before adapter call |

### Requirement: Auth port and swappable adapters

`lib/auth/port.ts` MUST define the auth interface with `getUserByEmail`, `createUser`, `createGuestUser`, `getTenantByUser`, `createTenant`, and `listTenantsForUser`. An in-memory adapter MUST implement this interface by delegating to `lib/db/queries.ts` (existing per-process store). A Clerk adapter STUB MUST expose the same signatures and MUST throw/return not-implemented, ready for a later swap.

| Scenario | GIVEN | WHEN | THEN |
|----------|-------|------|------|
| In-memory delegate | In-memory adapter selected | Any port method is called | The call delegates to `lib/db/queries.ts` and returns its result |
| Clerk stub | Clerk adapter selected | Any port method is called | It throws not-implemented without affecting the UI |
| Swap without UI changes | UI consumes only `useAuth()` | The active adapter changes | No UI file changes are required |

### Requirement: AuthProvider client and useAuth()

The client `AuthProvider` MUST expose `{ user, tenant, status, isGuest, signIn, signOut, createTenant, switchTenant }` and MUST be seeded from serializable server props fetched in `app/(chat)/layout.tsx` behind `<Suspense>` (Next 16 `cookies()`/`headers()` render-blocking constraint). `signIn`/`signOut` MUST be wrapped in server actions that update the session and call `router.refresh()` to prevent `auth()`/`useSession()` drift. The session/JWT SHALL carry only `tenantId` — never the full tenant object. `useAuth()` MUST be consumed only inside the provider tree.

| Scenario | GIVEN | WHEN | THEN |
|----------|-------|------|------|
| Seed from server | `(chat)/layout` loads | Server fetch resolves behind `<Suspense>` | `AuthProvider` initializes with `status: "authenticated"` and serializable user, no hydration flash |
| Sign-in mutation | User submits credentials | `signIn` server action runs | Session updates and UI reflects the new user without a full reload |
| Lean session | User has a tenant | Session/JWT is issued | Only `tenantId` is carried, not the full tenant |

## Capability: auth-tenant

### Requirement: Create tenant

The system MUST let an authenticated user create a tenant by name via `createTenant`, persist it in the in-memory mock, and surface the result in the chat UI.

| Scenario | GIVEN | WHEN | THEN |
|----------|-------|------|------|
| Tenant created | Authenticated user submits a tenant name | `createTenant` succeeds | The tenant appears in the chat UI and a `tenantCreated` toast is shown |
| Empty name | Create-tenant form opened | User submits without a name | Validation error, no tenant is created |

### Requirement: Show and switch current tenant

The current tenant MUST be displayed in the chat header / `sidebar-user-nav`, and a user with multiple tenants MUST be able to switch between them. Consumers MUST read user/tenant via the client `useAuth()` hook (seeded from serializable server props behind `<Suspense>`, per REQ-3) — the legacy `user` prop-drill from the chat layout is removed. Guest users MUST NOT be able to create tenants (gated to `regular`).

| Scenario | GIVEN | WHEN | THEN |
|----------|-------|------|------|
| Single tenant | User has one tenant | Chat renders | Current tenant name is shown in header/sidebar |
| Switch tenant | User has multiple tenants | They pick another tenant | Header updates to the new tenant without a full reload |
| No tenant | Guest or user without tenants | Chat renders | A `noTenants` placeholder is shown |

### Requirement: i18n keys for tenant UI

The system MUST ship `panel.tenant.*` keys in both EN and ES dictionaries together: `createTenant`, `currentTenant`, `tenantName`, `switchTenant`, `tenantCreated`, `noTenants`, `placeholder`. No dictionary drift is allowed — both locales update in the same change.

| Scenario | GIVEN | WHEN | THEN |
|----------|-------|------|------|
| Spanish default | Locale `es` active | Tenant UI renders | Labels/placeholders show Spanish copy (e.g. "Crear tenant") |
| English switch | Locale `en` active | Tenant UI renders | Labels/placeholders show English copy, no mixed partial strings |

### Requirement: Mock persistence lifecycle

Tenants MUST be stored in memory only (via the `lib/db/queries.ts` per-process store). All tenants MUST be lost when the server restarts; the UI MUST then show the `noTenants` state until a new tenant is created.

| Scenario | GIVEN | WHEN | THEN |
|----------|-------|------|------|
| Restart wipes tenants | A user created tenants | The server restarts | No tenant remains; UI shows `noTenants`, user creates again |

## Out of Scope

Clerk/real backend connection (adapter stub only), PostgreSQL/Drizzle migrations, UI redesign, chat content features.
