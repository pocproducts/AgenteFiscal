# Proposal: Cambio de clean architecture para auth + tenant

## Intent

Auth está acoplada a next-auth v5 y a la DB in-memory (`lib/db/queries.ts`): `User` no tiene `tenantId` ni rol, no hay tenant que crear/mostrar/cambiar en el chat. Objetivo: UI fluida AHORA sobre el mock in-memory, detrás de una frontera port/adapter para SWAPEAR a Clerk/backend real mañana sin tocar la UI. (Technical artifact — English detail below; user-visible copy via i18n.)

## Objective (Why)

- Fluid UI on in-memory mock: register/login any email (pass ≥6), create tenant, show current tenant in chat.
- Clean-architecture boundary so `in-memory` → `clerk` adapter swap does not touch UI.

## Scope

### In Scope
- Port/adapter layer `lib/auth/port.ts` + in-memory adapter (guest, register/login, tenant ops).
- Tenant lifecycle: register/login, create tenant (name), show current tenant in chat.
- Client `AuthProvider` → `useAuth()`.
- i18n `panel.tenant.*`.
- Server seed in `app/(chat)/layout.tsx` behind `<Suspense>`.

### Out of Scope
- Connecting Clerk/real backend now (adapter stub only).
- Real PostgreSQL / multi-tenant DB; Drizzle migrations.
- UI redesign; chat content features.

## Capabilities

### New Capabilities
- `auth-core`: port (`lib/auth/port.ts`) + in-memory adapter, `AuthProvider`/`useAuth`: `{ user, tenant, status, isGuest, signIn, signOut, createTenant, switchTenant }`; guest + register/login (email, pass≥6).
- `auth-tenant`: tenant create/switch; `panel.tenant.*` keys; tenant display in `sidebar-user-nav`/chat header.

### Modified Capabilities
- None (`openspec/specs/` empty).

## Approach / Key decisions (first draft)

- Single source of truth: server fetch in `(chat)/layout.tsx` → serializable props → client `AuthProvider` (no direct server-component mount; avoids Next 16 `cookies()`/`headers()` render-blocking).
- Mutations via server actions wrapping next-auth `signIn/signOut`; `updateSession()` + `router.refresh()` after mutate (kills auth()/useSession() divergence).
- JWT carries only `id` + `type` + `tenantId` — no inflated tenant.
- Adapter swap via same interface: `in-memory` today, `clerk` stub later; UI only consumes `useAuth()`.
- Settle shape in design phase.

## Affected areas

| Area | Impact | Description |
|------|--------|-------------|
| `lib/auth/port.ts`, `adapters/in-memory.ts` | New | Port + adapter |
| `app/(chat)/layout.tsx` | Modified | Server seed behind `<Suspense>` |
| `app/(chat)/components/sidebar-user-nav.tsx` | Modified | Tenant display + create/switch |
| `app/(auth)/actions.ts` | Modified | Wrap mutations + refresh |
| `lib/i18n/dictionary.ts` | Modified | `panel.tenant.*` (en/es) |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Next 16 render-blocking cookies/headers | Med | Seed behind Suspense; serializable props |
| auth()+useSession() drift | Med | Single mutation path + refresh |
| EN/ES dict drift | Low | Keys shipped together |

## Rollback Plan

- `git revert` change; UI keeps working against current next-auth + mock DB (adapter isolates swap risk).

## Dependencies

- None new. Build/test run by user (`pnpm build`, `pnpm test`).

## Success criteria

- Register/login any email (pass≥6) works in-memory.
- Tenant created and shown in chat; switch reflects without full reload.
- Mock empties on server restart.
- `pnpm build` + `pnpm test` green (user-run).